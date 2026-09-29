"""Evolução entre partidas: defesa (Caçador) e ataque (Mutante).

DEFESA: cada teste do Caçador que mata um mutante é salvo em progresso/suite/.
Na partida seguinte, esses testes já fazem parte da suíte que o Mutante precisa enganar.

ATAQUE: cada mutação tentada vira uma lição em progresso/arsenal.json (sobreviveu,
foi abatida, foi detectada pela suíte, era equivalente ou inválida). No início de
cada turno o Mutante recebe essa memória: explora brechas que já funcionaram e
evita o que a defesa já cobre.

    progresso/
    ├── suite/             ← testes herdados (um arquivo por mutante abatido)
    ├── arsenal.json       ← memória de ataques do Mutante
    └── historico.json     ← uma entrada por partida (placar e níveis)

Os pesos dos LLMs não mudam: evoluem a DEFESA acumulada e a MEMÓRIA do atacante.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

RAIZ = Path(__file__).parent
DIR = RAIZ / "progresso"
DIR_SUITE = DIR / "suite"
HISTORICO = DIR / "historico.json"
ARSENAL = DIR / "arsenal.json"

# Resultados de um ataque que ensinam algo ao Mutante (erros de formato também, para não repetir).
RESULTADOS = {
    "sobreviveu": "✅ SOBREVIVEU (o Caçador não detectou): brecha da defesa, explore de novo ou varie",
    "abatido": "🏹 ABATIDO pelo Caçador (agora há teste para isso): não repita",
    "morto_pela_suite": "🛡️ DETECTADO pela suíte existente: não repita",
    "mutante_equivalente": "〰️ EQUIVALENTE (não mudou o comportamento): não repita",
}


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.strip().encode("utf-8")).hexdigest()[:12]


def carregar_herdados() -> dict[str, str]:
    """Testes acumulados de partidas anteriores, em ordem de criação."""
    if not DIR_SUITE.exists():
        return {}
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(DIR_SUITE.glob("test_*.py"))}


def nivel(qtd_herdados: int | None = None) -> int:
    """Nível da defesa = 1 + testes herdados de partidas anteriores."""
    if qtd_herdados is None:
        qtd_herdados = len(carregar_herdados())
    return 1 + qtd_herdados


def salvar_teste(partida: str, rodada: int, codigo: str) -> str | None:
    """Guarda um teste vencedor. Ignora duplicatas exatas. Devolve o nome do arquivo."""
    DIR_SUITE.mkdir(parents=True, exist_ok=True)
    marca = f"[sha:{_hash(codigo)}]"  # assinatura do conteúdo, gravada no cabeçalho
    for existente in DIR_SUITE.glob("test_*.py"):
        if marca in existente.read_text(encoding="utf-8").splitlines()[0]:
            return None
    # Nome curto e sequencial (caminhos longos quebram no Windows); a origem vai no cabeçalho.
    numeros = [int(p.stem[5:]) for p in DIR_SUITE.glob("test_*.py") if p.stem[5:].isdigit()]
    nome = f"test_{max(numeros, default=0) + 1:03d}.py"
    cabecalho = f'"""Teste herdado: matou o mutante da rodada {rodada} da partida {partida}. {marca}"""\n'
    (DIR_SUITE / nome).write_text(cabecalho + codigo, encoding="utf-8")
    return nome


def _ler_json(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


# ------------------------------------------------------------ ataque (Mutante)

def carregar_arsenal() -> list[dict]:
    return _ler_json(ARSENAL)


def registrar_ataque(partida: str, rodada: int, linha: int, trecho_original: str, trecho_novo: str,
                     resultado: str, detalhe: str = "") -> None:
    """Guarda o resultado de uma mutação tentada (lição para as próximas)."""
    arsenal = carregar_arsenal()
    arsenal.append({"partida": partida, "rodada": rodada, "linha": linha,
                    "trecho_original": trecho_original, "trecho_novo": trecho_novo,
                    "resultado": resultado, "detalhe": detalhe[:160]})
    DIR.mkdir(parents=True, exist_ok=True)
    ARSENAL.write_text(json.dumps(arsenal, ensure_ascii=False, indent=2), encoding="utf-8")


def _chave(a: dict) -> tuple:
    return (a["linha"], a["trecho_original"].strip(), a["trecho_novo"].strip())


def licoes(arsenal: list[dict] | None = None) -> dict[tuple, dict]:
    """Uma lição por ataque distinto (linha + troca); vale o resultado mais recente."""
    arsenal = carregar_arsenal() if arsenal is None else arsenal
    unicas: dict[tuple, dict] = {}
    for a in arsenal:
        unicas[_chave(a)] = a
    return unicas


def nivel_ataque(arsenal: list[dict] | None = None) -> int:
    """Nível do ataque = 1 + brechas descobertas (mutações distintas que já sobreviveram).

    Mesma régua da defesa (1 + mutantes abatidos): cada lado só sobe de nível quando VENCE
    uma rodada. Assim dá para comparar quem evolui mais."""
    arsenal = carregar_arsenal() if arsenal is None else arsenal
    return 1 + len({_chave(a) for a in arsenal if a["resultado"] == "sobreviveu"})


def memoria_mutante(max_por_grupo: int = 6) -> list[str]:
    """Texto que o Mutante recebe no início do turno, agrupado por resultado."""
    unicas = licoes()
    if not unicas:
        return []
    linhas: list[str] = []
    ordem = ["sobreviveu", "abatido", "morto_pela_suite", "mutante_equivalente"]
    for resultado in ordem + ["erro"]:
        grupo = [a for a in unicas.values()
                 if (a["resultado"] == resultado) or (resultado == "erro" and a["resultado"] not in ordem)]
        if not grupo:
            continue
        titulo = RESULTADOS.get(resultado, "⚠️ ERRO de formato (evite repetir)")
        linhas.append(titulo + ":")
        for a in grupo[-max_por_grupo:]:
            motivo = f" [{a['resultado']}]" if resultado == "erro" else ""
            linhas.append(f"  - linha {a['linha']}: \"{a['trecho_original']}\" -> \"{a['trecho_novo']}\"{motivo}")
    return linhas


# ------------------------------------------------------------ histórico

def carregar_historico() -> list[dict]:
    return _ler_json(HISTORICO)


def registrar_partida(**dados) -> None:
    historico = carregar_historico()
    historico.append({"data": time.strftime("%Y-%m-%d %H:%M"), **dados})
    DIR.mkdir(parents=True, exist_ok=True)
    HISTORICO.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


def zerar() -> int:
    """Apaga a suíte herdada, a memória do Mutante e o histórico. Devolve quantos testes foram removidos."""
    removidos = 0
    for p in DIR_SUITE.glob("test_*.py"):
        p.unlink()
        removidos += 1
    for arq in (HISTORICO, ARSENAL):
        if arq.exists():
            arq.unlink()
    return removidos


def situacao() -> dict:
    """Resumo para o painel e para o terminal."""
    herdados = carregar_herdados()
    historico = carregar_historico()
    arsenal = carregar_arsenal()
    return {
        "nivel": nivel(len(herdados)),
        "nivel_ataque": nivel_ataque(arsenal),
        "licoes": len(licoes(arsenal)),
        "testes_herdados": len(herdados),
        "partidas": len(historico),
        "historico": historico[-20:],
    }
