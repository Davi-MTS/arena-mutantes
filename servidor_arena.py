"""Servidor MCP da Arena: Mutante vs. Caçador.

Expõe as ferramentas do jogo via Model Context Protocol (transporte stdio).
As regras (de quem é o turno, quantas tentativas, quem pontua) são impostas
AQUI, no servidor — não dependem de o agente "obedecer" ao prompt.

Ferramentas dos agentes : ler_codigo, ler_testes, propor_mutacao, enviar_teste
Ferramentas do orquestrador (nunca expostas ao LLM): admin_*
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import arbitro

RAIZ = Path(__file__).parent
ORIGINAL = (RAIZ / "campo" / "descontos.py").read_text(encoding="utf-8")
TESTES_BASE = {"test_base.py": (RAIZ / "campo" / "test_base.py").read_text(encoding="utf-8")}
MAX_TENTATIVAS = int(os.environ.get("ARENA_MAX_TENTATIVAS", "3"))
LOG_ARBITRO = Path(os.environ.get("ARENA_LOG_ARBITRO", RAIZ / "logs" / "arbitro.jsonl"))
LOG_ARBITRO.parent.mkdir(parents=True, exist_ok=True)

estado = {
    "rodada": 0,
    "turno": None,            # "mutante" | "cacador" | None
    "codigo_atual": ORIGINAL,
    "mutacao": None,
    "tentativas": 0,
    "testes_aceitos": {},     # testes do Caçador que mataram mutantes (a suíte evolui)
    "placar": {"mutante": 0, "cacador": 0},
    "resultado_rodada": None,
}

mcp = FastMCP("arena-mutantes", log_level="WARNING")


def _log(evento: str, **dados) -> None:
    registro = {"ts": time.time(), "rodada": estado["rodada"], "evento": evento, **dados}
    with LOG_ARBITRO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _resp(**dados) -> str:
    return json.dumps(dados, ensure_ascii=False)


def _suite() -> dict[str, str]:
    return {**TESTES_BASE, **estado["testes_aceitos"]}


def _encerrar(vencedor: str, motivo: str) -> None:
    estado["placar"][vencedor] += 1
    estado["turno"] = None
    estado["resultado_rodada"] = {"vencedor": vencedor, "motivo": motivo}
    _log("fim_rodada", vencedor=vencedor, motivo=motivo, placar=dict(estado["placar"]))


# ------------------------------------------------------- ferramentas do jogo

@mcp.tool()
def ler_codigo() -> str:
    """Retorna o código atual de descontos.py com números de linha.
    As docstrings são a ESPECIFICAÇÃO correta do comportamento."""
    linhas = estado["codigo_atual"].splitlines()
    numerado = "\n".join(f"{i:>3}| {t}" for i, t in enumerate(linhas, start=1))
    extra = ""
    if estado["turno"] == "mutante":
        editaveis = sorted(arbitro.linhas_editaveis(estado["codigo_atual"]))
        extra = f"\n\nLinhas que você pode alterar: {editaveis}"
    return numerado + extra


@mcp.tool()
def ler_testes() -> str:
    """Retorna todos os testes automatizados atuais da suíte."""
    return "\n\n".join(f"# ===== {nome} =====\n{codigo}" for nome, codigo in _suite().items())


@mcp.tool()
def propor_mutacao(numero_linha: int, nova_linha: str, justificativa: str = "") -> str:
    """[MUTANTE] Substitui UMA linha de descontos.py por uma versão com bug sutil.
    Regras: não pode alterar docstrings nem 'def'; sem comentários; o mutante
    precisa mudar o comportamento E passar em todos os testes atuais."""
    if estado["turno"] != "mutante":
        _log("violacao_turno", ferramenta="propor_mutacao", turno=estado["turno"])
        return _resp(aceita=False, erro="não é o turno do Mutante", turno_encerrado=True)

    estado["tentativas"] += 1
    restantes = MAX_TENTATIVAS - estado["tentativas"]

    def rejeitar(motivo: str, detalhe: str) -> str:
        _log("mutacao_rejeitada", tentativa=estado["tentativas"], motivo=motivo, detalhe=detalhe,
             numero_linha=numero_linha, nova_linha=nova_linha, justificativa=justificativa)
        if restantes <= 0:
            _encerrar("cacador", f"Mutante esgotou as tentativas (última: {motivo})")
            return _resp(aceita=False, motivo=motivo, detalhe=detalhe, tentativas_restantes=0,
                         turno_encerrado=True)
        return _resp(aceita=False, motivo=motivo, detalhe=detalhe, tentativas_restantes=restantes,
                     turno_encerrado=False)

    try:
        numero_linha = int(numero_linha)
    except (TypeError, ValueError):
        return rejeitar("argumento_invalido", "numero_linha precisa ser inteiro")

    veredito, mutado = arbitro.validar_mutacao(ORIGINAL, numero_linha, str(nova_linha))
    if not veredito.ok:
        return rejeitar(veredito.motivo, veredito.detalhe)

    muda, evidencia = arbitro.oraculo_diferencial(ORIGINAL, mutado)
    if not muda:
        return rejeitar("mutante_equivalente",
                        f"a mudança não altera o comportamento ({evidencia}); tente outra")

    passou, saida = arbitro.rodar_pytest(mutado, _suite())
    if not passou:
        return rejeitar("morto_pela_suite", f"os testes atuais já detectam esse bug:\n{saida[-600:]}")

    estado["codigo_atual"] = mutado
    estado["mutacao"] = {"linha": numero_linha, "descricao": veredito.detalhe, "evidencia": evidencia}
    estado["turno"] = None
    _log("mutacao_aceita", tentativa=estado["tentativas"], descricao=veredito.detalhe,
         evidencia_oraculo=evidencia, justificativa=justificativa)
    return _resp(aceita=True, detalhe="mutante sobreviveu à suíte atual e está vivo",
                 turno_encerrado=True)


@mcp.tool()
def enviar_teste(codigo: str, justificativa: str = "") -> str:
    """[CAÇADOR] Envia um arquivo de teste pytest (importando de 'descontos').
    O teste precisa PASSAR no código correto (especificação) e FALHAR no código
    com bug para matar o mutante."""
    if estado["turno"] != "cacador":
        _log("violacao_turno", ferramenta="enviar_teste", turno=estado["turno"])
        return _resp(matou=False, erro="não é o turno do Caçador", turno_encerrado=True)

    estado["tentativas"] += 1
    restantes = MAX_TENTATIVAS - estado["tentativas"]

    def falhar(motivo: str, detalhe: str, detalhe_log: str = "") -> str:
        _log("teste_rejeitado", tentativa=estado["tentativas"], motivo=motivo,
             detalhe=detalhe_log or detalhe, codigo=codigo, justificativa=justificativa)
        if restantes <= 0:
            _encerrar("mutante", f"Caçador esgotou as tentativas (última: {motivo})")
            return _resp(matou=False, motivo=motivo, detalhe=detalhe, tentativas_restantes=0,
                         turno_encerrado=True)
        return _resp(matou=False, motivo=motivo, detalhe=detalhe, tentativas_restantes=restantes,
                     turno_encerrado=False)

    veredito = arbitro.validar_teste(str(codigo))
    if not veredito.ok:
        return falhar(veredito.motivo, veredito.detalhe)

    nome = f"test_cacador_r{estado['rodada']}.py"
    todas = arbitro.funcoes_de_teste(codigo)
    # 1) Filtro de alucinação: testes que falham no código CORRETO contradizem a
    #    especificação e são descartados, função por função.
    alucinados, saida_original = arbitro.testes_que_falham(ORIGINAL, nome, codigo)
    if alucinados:
        _log("testes_alucinados", tentativa=estado["tentativas"], funcoes=sorted(alucinados),
             total=len(todas), saida=saida_original)
    validos = [t for t in todas if t not in alucinados]
    if not validos:
        # Não devolvemos os valores esperados: o código original não pode virar oráculo do Caçador.
        return falhar("expectativa_errada",
                      f"todos os seus {len(todas)} testes FALHAM no código correto: as expectativas contradizem "
                      "a especificação (docstrings). Recalcule os valores esperados pela docstring.",
                      detalhe_log=saida_original)
    codigo_filtrado = arbitro.remover_funcoes(codigo, alucinados) if alucinados else codigo
    aviso = (f" {len(alucinados)} de {len(todas)} testes foram descartados por contradizerem a especificação: "
             f"{sorted(alucinados)}." if alucinados else "")

    # 2) Os testes válidos detectam o mutante?
    ok_mutante, saida_mutante = arbitro.rodar_pytest(estado["codigo_atual"], {nome: codigo_filtrado})
    if ok_mutante:
        return falhar("nao_detectou", "seus testes válidos passam no código com bug: não detectam o mutante."
                      + aviso + " O bug está em outra regra ou outro valor-limite: cubra mais funções e limites.")

    estado["testes_aceitos"][nome] = codigo_filtrado
    _log("mutante_morto", tentativa=estado["tentativas"], teste=nome, saida=saida_mutante,
         validos=len(validos), descartados=len(alucinados), justificativa=justificativa)
    _encerrar("cacador", "teste do Caçador matou o mutante")
    return _resp(matou=True, detalhe="mutante morto! seus testes válidos entraram na suíte." + aviso,
                 turno_encerrado=True)


# ----------------------------------------- ferramentas do orquestrador (admin)

@mcp.tool()
def admin_nova_rodada() -> str:
    """[ORQUESTRADOR] Restaura o código original e abre o turno do Mutante."""
    estado.update(rodada=estado["rodada"] + 1, turno="mutante", codigo_atual=ORIGINAL,
                  mutacao=None, tentativas=0, resultado_rodada=None)
    _log("inicio_rodada", testes_na_suite=len(_suite()))
    return _resp(rodada=estado["rodada"], testes_na_suite=len(_suite()))


@mcp.tool()
def admin_abrir_turno_cacador() -> str:
    """[ORQUESTRADOR] Passa a vez ao Caçador se houver mutante vivo."""
    if estado["mutacao"] is None:
        return _resp(aberto=False, motivo="não há mutante vivo")
    estado.update(turno="cacador", tentativas=0)
    return _resp(aberto=True)


@mcp.tool()
def admin_encerrar_por_limite() -> str:
    """[ORQUESTRADOR] Encerra o turno de um agente que estourou o limite de passos
    (limite de autonomia). O ponto vai para o adversário."""
    if estado["turno"] == "mutante":
        _encerrar("cacador", "Mutante estourou o limite de passos")
    elif estado["turno"] == "cacador":
        _encerrar("mutante", "Caçador estourou o limite de passos")
    else:
        return _resp(encerrado=False)
    return _resp(encerrado=True)


@mcp.tool()
def admin_estado() -> str:
    """[ORQUESTRADOR] Placar e resultado da última rodada (inclui o gabarito)."""
    return _resp(rodada=estado["rodada"], placar=estado["placar"], mutacao=estado["mutacao"],
                 resultado_rodada=estado["resultado_rodada"],
                 testes_aceitos=list(estado["testes_aceitos"]))


if __name__ == "__main__":
    mcp.run()
