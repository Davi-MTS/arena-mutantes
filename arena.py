"""Arena de agentes autônomos: Mutante vs. Caçador (100% local via Ollama + MCP).

Uso:
    python arena.py --rodadas 3
    python arena.py --modelo-mutante qwen3:4b --modelo-cacador qwen2.5-coder:7b

Cada agente é um LLM local que só enxerga o mundo pelas ferramentas MCP do
seu papel. Tudo o que acontece é registrado em logs/<partida>/*.jsonl.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

RAIZ = Path(__file__).parent
console = Console()

# Lista de permissões por papel: o LLM só recebe (e só pode chamar) estas.
FERRAMENTAS_POR_PAPEL = {
    "mutante": ["ler_codigo", "ler_testes", "propor_mutacao"],
    "cacador": ["ler_codigo", "ler_testes", "enviar_teste"],
}

PROMPTS = {
    "mutante": """Você é o MUTANTE em um jogo de testes de software. Objetivo: inserir UM bug sutil no arquivo descontos.py que os testes atuais NÃO consigam detectar.
Regras:
- Altere exatamente UMA linha de código, usando o número de linha mostrado por ler_codigo. Não altere docstrings nem linhas 'def'. Não use comentários.
- O bug precisa mudar o comportamento de verdade (mudanças equivalentes são rejeitadas).
- O bug precisa passar nos testes atuais: leia os testes e ataque o que NÃO é testado.
Ideias de bugs sutis: trocar >= por >, mudar uma constante (0.10 -> 0.01, 300 -> 30), trocar "GO" por "DF", trocar * por +, usar a variável errada.
Procedimento: 1) chame ler_codigo 2) chame ler_testes 3) chame propor_mutacao(numero_linha, nova_linha, justificativa). Se for rejeitada, leia o motivo e chame propor_mutacao de novo com outra ideia (não precisa reler o código).
Responda SEMPRE chamando uma ferramenta.""",
    "cacador": """Você é o CAÇADOR em um jogo de testes de software. Alguém alterou UMA linha de código de descontos.py e inseriu um bug. As docstrings NÃO foram alteradas: elas são a especificação correta.
Objetivo: escrever um teste pytest que PASSE no comportamento correto (docstring) e FALHE no código atual com bug.
ATENÇÃO: os testes atuais PASSAM no código com bug. Copiá-los é inútil: escreva testes NOVOS.
Estratégia vencedora: escreva VÁRIAS funções de teste pequenas, uma por regra (ex.: test_volume_100, test_cupom_menos20_99), cobrindo TODAS as regras das docstrings, especialmente os valores exatamente nos limites. O árbitro descarta as funções com expectativa errada e usa as válidas:
- desconto_volume: 49, 50, 99, 100 unidades
- aplicar_cupom: cada cupom, valores 99.99 e 100.0, cupom desconhecido e None
- frete: GO com 299.99 e 300.0, DF, outra UF
- subtotal e total_pedido com exemplos calculados à mão
Procedimento: 1) chame ler_codigo 2) calcule os valores esperados SOMENTE pela docstring 3) chame enviar_teste(codigo, justificativa).
O teste deve começar com "from descontos import ...", definir funções test_..., e usar apenas assert. Não importe outros módulos.
Se o teste for rejeitado, leia o motivo, corrija e envie de novo (não precisa reler o código).
Responda SEMPRE chamando uma ferramenta.""",
}

TAREFA = {
    "mutante": "Nova rodada. Insira um bug sutil que sobreviva aos testes atuais.",
    "cacador": "Um mutante está vivo em descontos.py. Encontre-o e mate-o com um teste.",
}

LEMBRETE = ('Você não chamou nenhuma ferramenta. Responda APENAS com uma chamada de ferramenta, '
            'no formato {"name": "<ferramenta>", "arguments": {...}}.')

ICONE = {"mutante": "🧟 Mutante", "cacador": "🏹 Caçador"}


class Registro:
    """Log estruturado (JSONL) de todas as decisões dos agentes."""

    def __init__(self, pasta: Path):
        self.arquivo = pasta / "agentes.jsonl"
        self.eventos: list[dict] = []

    def __call__(self, evento: str, **dados):
        reg = {"ts": time.time(), "evento": evento, **dados}
        self.eventos.append(reg)
        with self.arquivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")


def extrair_chamadas(mensagem) -> tuple[list[tuple[str, dict]], str]:
    """Chamadas nativas do Ollama ou, se o modelo 'escreveu' a chamada como
    texto JSON (comum em modelos pequenos), faz o parse de reserva."""
    if mensagem.tool_calls:
        return [(c.function.name, dict(c.function.arguments or {})) for c in mensagem.tool_calls], "nativa"
    texto = mensagem.content or ""
    decoder = json.JSONDecoder()
    chamadas, i = [], 0
    while i < len(texto):
        if texto[i] in "{[":
            try:
                obj, fim = decoder.raw_decode(texto, i)
            except json.JSONDecodeError:
                i += 1
                continue
            for item in obj if isinstance(obj, list) else [obj]:
                if isinstance(item, dict) and "function" in item and isinstance(item["function"], dict):
                    item = item["function"]
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    args = item.get("arguments", item.get("parameters", {}))
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    chamadas.append((item["name"], args if isinstance(args, dict) else {}))
            i = fim
        else:
            i += 1
    return chamadas, "texto_json" if chamadas else "nenhuma"


def resumir(texto: str, n: int = 160) -> str:
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= n else texto[: n - 1] + "…"


async def turno(sessao: ClientSession, ferramentas: list[dict], papel: str, modelo: str,
                args, log: Registro, rodada: int) -> bool:
    """Executa o turno autônomo de um agente. Retorna True se o turno terminou
    pelas regras do jogo, False se estourou o limite de passos."""
    permitidas = FERRAMENTAS_POR_PAPEL[papel]
    tools = [f for f in ferramentas if f["function"]["name"] in permitidas]
    msgs = [{"role": "system", "content": PROMPTS[papel]}, {"role": "user", "content": TAREFA[papel]}]
    opcoes = {"num_ctx": args.num_ctx, "temperature": 0.8 if papel == "mutante" else 0.2}
    extra = {"think": False} if modelo.startswith("qwen3") else {}
    ja_lido: dict[str, str] = {}

    for passo in range(1, args.max_passos + 1):
        inicio = time.time()
        r = await asyncio.to_thread(ollama.chat, model=modelo, messages=msgs, tools=tools,
                                    options=opcoes, **extra)
        duracao = time.time() - inicio
        tok_s = (r.eval_count or 0) / ((r.eval_duration or 1) / 1e9)
        chamadas, origem = extrair_chamadas(r.message)
        log("llm_resposta", rodada=rodada, papel=papel, modelo=modelo, passo=passo,
            conteudo=r.message.content, origem_chamada=origem, chamadas=chamadas,
            tokens_prompt=r.prompt_eval_count, tokens_gerados=r.eval_count,
            tokens_por_s=round(tok_s, 1), segundos=round(duracao, 1))

        if origem == "nativa":
            msgs.append(r.message)
        else:
            msgs.append({"role": "assistant", "content": r.message.content or ""})

        if not chamadas:
            console.print(f"   [yellow]{ICONE[papel]} respondeu sem chamar ferramenta[/] "
                          f"[dim]({resumir(r.message.content, 90)})[/]")
            msgs.append({"role": "user", "content": LEMBRETE})
            continue

        # Modelos pequenos costumam planejar várias chamadas numa resposta só:
        # executamos em ordem (até 4) e paramos quando o turno termina.
        for nome, argumentos in chamadas[:4]:
            if nome not in permitidas:
                log("ferramenta_bloqueada", rodada=rodada, papel=papel, ferramenta=nome, argumentos=argumentos)
                console.print(f"   [red]⛔ {ICONE[papel]} tentou usar '{nome}' (fora da sua permissão)[/]")
                msgs.append({"role": "tool", "content": json.dumps(
                    {"erro": f"ferramenta '{nome}' não permitida para o papel {papel}. Use: {permitidas}"})})
                continue

            console.print(f"   {ICONE[papel]} → [bold cyan]{nome}[/]"
                          f"({resumir(json.dumps(argumentos, ensure_ascii=False), 110) if argumentos else ''})"
                          f" [dim]{duracao:.0f}s · {tok_s:.0f} tok/s · {origem}[/]")
            try:
                resultado = await sessao.call_tool(nome, argumentos)
                texto = "\n".join(getattr(c, "text", "") for c in resultado.content)
            except Exception as e:  # argumentos inválidos gerados pelo modelo
                texto = json.dumps({"erro": f"chamada inválida: {e}"}, ensure_ascii=False)
            log("ferramenta_resultado", rodada=rodada, papel=papel, ferramenta=nome,
                argumentos=argumentos, resultado=texto)
            if nome.startswith("ler_") and ja_lido.get(nome) == texto:
                # Economia de contexto: releitura idêntica não é repetida no histórico.
                msgs.append({"role": "tool", "tool_name": nome,
                             "content": "(conteúdo idêntico à leitura anterior, que já está acima)"})
            else:
                ja_lido[nome] = texto
                msgs.append({"role": "tool", "content": texto, "tool_name": nome})

            try:
                dados = json.loads(texto)
            except json.JSONDecodeError:
                dados = None
            if isinstance(dados, dict):
                cor = "green" if dados.get("aceita") or dados.get("matou") else "red"
                if "aceita" in dados or "matou" in dados or "erro" in dados:
                    msg = dados.get("detalhe") or dados.get("erro") or ""
                    console.print(f"      [{cor}]⚖ árbitro: {dados.get('motivo', '')} {resumir(msg, 140)}[/]")
                if dados.get("turno_encerrado"):
                    return True

    log("limite_de_passos", rodada=rodada, papel=papel)
    console.print(f"   [red]⏱ {ICONE[papel]} estourou o limite de {args.max_passos} passos[/]")
    return False


async def partida(args):
    pasta = RAIZ / "logs" / time.strftime("%Y%m%d_%H%M%S")
    pasta.mkdir(parents=True, exist_ok=True)
    log = Registro(pasta)

    # O servidor MCP roda com ambiente mínimo: nenhum segredo do usuário é repassado.
    env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "WINDIR")}
    env.update(ARENA_LOG_ARBITRO=str(pasta / "arbitro.jsonl"), ARENA_MAX_TENTATIVAS=str(args.tentativas),
               PYTHONIOENCODING="utf-8")
    servidor = StdioServerParameters(command=sys.executable, args=[str(RAIZ / "servidor_arena.py")],
                                     env=env, cwd=str(RAIZ))

    modelos = {"mutante": args.modelo_mutante or args.modelo, "cacador": args.modelo_cacador or args.modelo}
    console.print(Panel.fit(
        f"[bold]ARENA: Mutante vs. Caçador[/]\n🧟 Mutante: {modelos['mutante']}   🏹 Caçador: {modelos['cacador']}\n"
        f"Rodadas: {args.rodadas} · 100% local (Ollama) · ferramentas via MCP", border_style="magenta"))
    log("inicio_partida", modelos=modelos, argumentos=vars(args))
    with console.status("Carregando modelos na GPU..."):
        for m in set(modelos.values()):
            await asyncio.to_thread(ollama.generate, model=m, prompt="", keep_alive="30m")
    inicio_partida = time.time()

    async with stdio_client(servidor) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()
            lista = await sessao.list_tools()
            ferramentas = [{"type": "function", "function": {
                "name": t.name, "description": t.description or "", "parameters": t.inputSchema}}
                for t in lista.tools]
            log("ferramentas_mcp", nomes=[t.name for t in lista.tools])

            async def admin(nome):
                r = await sessao.call_tool(nome, {})
                return json.loads(r.content[0].text)

            for rodada in range(1, args.rodadas + 1):
                info = await admin("admin_nova_rodada")
                console.rule(f"[bold]Rodada {rodada}[/] · testes na suíte: {info['testes_na_suite']}")

                if not await turno(sessao, ferramentas, "mutante", modelos["mutante"], args, log, rodada):
                    await admin("admin_encerrar_por_limite")

                abertura = await admin("admin_abrir_turno_cacador")
                if abertura["aberto"]:
                    gabarito = (await admin("admin_estado"))["mutacao"]
                    console.print(Panel(f"[bold red]Bug inserido[/] (o Caçador NÃO vê isto):\n{gabarito['descricao']}\n"
                                        f"[dim]prova do oráculo: {gabarito['evidencia']}[/]", border_style="red"))
                    if not await turno(sessao, ferramentas, "cacador", modelos["cacador"], args, log, rodada):
                        await admin("admin_encerrar_por_limite")

                final = await admin("admin_estado")
                res = final["resultado_rodada"] or {}
                console.print(f"   🏁 [bold]{res.get('vencedor', '?').upper()}[/] vence a rodada: {res.get('motivo', '')}"
                              f"   [dim]placar {final['placar']}[/]")
                log("fim_rodada", **final)

            final = await admin("admin_estado")

    resumo = gerar_resumo(log.eventos, pasta, final, modelos, time.time() - inicio_partida)
    mostrar_resumo(resumo)
    console.print(f"\n[dim]Logs: {pasta}[/]")


def gerar_resumo(eventos: list[dict], pasta: Path, final: dict, modelos: dict, duracao: float) -> dict:
    arbitro = []
    arq = pasta / "arbitro.jsonl"
    if arq.exists():
        arbitro = [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]
    respostas = [e for e in eventos if e["evento"] == "llm_resposta"]
    por_papel = {}
    for papel in ("mutante", "cacador"):
        rs = [e for e in respostas if e["papel"] == papel]
        por_papel[papel] = {
            "modelo": modelos[papel],
            "chamadas_llm": len(rs),
            "tokens_gerados": sum(e["tokens_gerados"] or 0 for e in rs),
            "tokens_por_s_medio": round(sum(e["tokens_por_s"] for e in rs) / len(rs), 1) if rs else 0,
            "chamadas_nativas": sum(e["origem_chamada"] == "nativa" for e in rs),
            "chamadas_via_texto_json": sum(e["origem_chamada"] == "texto_json" for e in rs),
            "respostas_sem_ferramenta": sum(e["origem_chamada"] == "nenhuma" for e in rs),
        }
    rejeicoes = Counter(f"{e['evento']}:{e['motivo']}" for e in arbitro
                        if e["evento"] in ("mutacao_rejeitada", "teste_rejeitado"))
    resumo = {
        "placar": final["placar"],
        "rodadas": final["rodada"],
        "duracao_s": round(duracao, 1),
        "agentes": por_papel,
        "rejeicoes_do_arbitro": dict(rejeicoes),
        "testes_alucinados_descartados": sum(len(e["funcoes"]) for e in arbitro if e["evento"] == "testes_alucinados"),
        "testes_enviados_total": sum(e.get("total", 0) for e in arbitro if e["evento"] == "testes_alucinados"),
        "ferramentas_bloqueadas": sum(e["evento"] == "ferramenta_bloqueada" for e in eventos),
        "limites_de_passos": sum(e["evento"] == "limite_de_passos" for e in eventos),
        "mutacoes_aceitas": [e["descricao"] for e in arbitro if e["evento"] == "mutacao_aceita"],
    }
    (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo


def mostrar_resumo(r: dict):
    t = Table(title=f"Resultado · {r['rodadas']} rodadas · {r['duracao_s']:.0f}s", show_lines=False)
    t.add_column("Métrica")
    t.add_column("🧟 Mutante", justify="right")
    t.add_column("🏹 Caçador", justify="right")
    m, c = r["agentes"]["mutante"], r["agentes"]["cacador"]
    t.add_row("Pontos", str(r["placar"]["mutante"]), str(r["placar"]["cacador"]))
    t.add_row("Modelo", m["modelo"], c["modelo"])
    for chave, rotulo in [("chamadas_llm", "Chamadas ao LLM"), ("tokens_gerados", "Tokens gerados"),
                          ("tokens_por_s_medio", "Tokens/s (média)"), ("chamadas_nativas", "Tool calls nativas"),
                          ("chamadas_via_texto_json", "Tool calls via texto (fallback)"),
                          ("respostas_sem_ferramenta", "Respostas sem ferramenta")]:
        t.add_row(rotulo, str(m[chave]), str(c[chave]))
    console.print(t)
    console.print(f"Funções de teste alucinadas (descartadas pelo árbitro): {r['testes_alucinados_descartados']}")
    if r["rejeicoes_do_arbitro"]:
        console.print("[bold]Erros/alucinações barrados pelo árbitro:[/]")
        for k, v in sorted(r["rejeicoes_do_arbitro"].items(), key=lambda x: -x[1]):
            console.print(f"   {v}× {k}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rodadas", type=int, default=3)
    p.add_argument("--modelo", default="qwen2.5-coder:7b")
    p.add_argument("--modelo-mutante")
    p.add_argument("--modelo-cacador")
    p.add_argument("--max-passos", type=int, default=12, help="limite de autonomia por turno")
    p.add_argument("--tentativas", type=int, default=3, help="tentativas de jogada por turno")
    p.add_argument("--num-ctx", type=int, default=6144)
    asyncio.run(partida(p.parse_args()))


if __name__ == "__main__":
    main()
