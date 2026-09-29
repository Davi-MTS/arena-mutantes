"""Árbitro determinístico da Arena.

Quem decide o resultado de cada jogada é a EXECUÇÃO de código, nunca um LLM:
  - validação estática (AST) de todo código gerado pelos agentes;
  - execução isolada em subprocesso, pasta temporária, timeout e ambiente
    sem segredos;
  - oráculo diferencial (original vs. mutante com milhares de entradas) para
    rejeitar mutantes equivalentes.
"""
from __future__ import annotations

import ast
import io
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_S = 30

# Nomes que código gerado por IA nunca pode usar (fuga da sandbox,
# leitura de segredos, rede, execução dinâmica).
NOMES_PROIBIDOS = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "input", "breakpoint",
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib",
    "builtins", "environ", "requests", "urllib", "http",
}
IMPORTS_PERMITIDOS_TESTE = {"descontos", "pytest", "math"}

PADRAO_NUMERO_LINHA = re.compile(r"^\s*\d+\s*[|:]\s?")


@dataclass
class Veredito:
    ok: bool
    motivo: str
    detalhe: str = ""


# ---------------------------------------------------------------- estático

def _checar_nomes(arvore: ast.AST) -> str | None:
    for no in ast.walk(arvore):
        if isinstance(no, ast.Name) and no.id in NOMES_PROIBIDOS:
            return f"uso proibido de '{no.id}'"
        if isinstance(no, ast.Attribute) and (
            no.attr in NOMES_PROIBIDOS or no.attr.startswith("__")
        ):
            return f"acesso proibido a atributo '{no.attr}'"
    return None


def linhas_editaveis(codigo: str) -> set[int]:
    """Linhas que o Mutante pode alterar: código de verdade, fora de docstrings,
    sem ser 'def' nem linha em branco."""
    arvore = ast.parse(codigo)
    bloqueadas: set[int] = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.FunctionDef)) and no.body:
            primeiro = no.body[0]
            if isinstance(primeiro, ast.Expr) and isinstance(
                getattr(primeiro, "value", None), ast.Constant
            ) and isinstance(primeiro.value.value, str):
                bloqueadas.update(range(primeiro.lineno, primeiro.end_lineno + 1))
        if isinstance(no, ast.FunctionDef):
            bloqueadas.add(no.lineno)
    linhas = codigo.splitlines()
    return {
        i for i, texto in enumerate(linhas, start=1)
        if texto.strip() and i not in bloqueadas
    }


def validar_mutacao(original: str, numero_linha: int, nova_linha: str) -> tuple[Veredito, str]:
    """Aplica a mutação numa cópia do código. Retorna (veredito, código_mutado)."""
    linhas = original.splitlines()
    if numero_linha not in linhas_editaveis(original):
        return Veredito(False, "linha_proibida",
                        f"linha {numero_linha} não é editável (docstring, def, vazia ou inexistente)"), ""

    nova = PADRAO_NUMERO_LINHA.sub("", nova_linha).rstrip()
    antiga = linhas[numero_linha - 1]
    indentacao = antiga[: len(antiga) - len(antiga.lstrip())]
    nova = indentacao + nova.strip()

    if "\n" in nova_linha.strip():
        return Veredito(False, "multiplas_linhas", "altere exatamente UMA linha"), ""
    if nova.strip() == antiga.strip():
        return Veredito(False, "sem_mudanca", "a nova linha é igual à original"), ""

    # Comentários/strings longas no código lido pelo outro agente são um vetor
    # de prompt injection ENTRE agentes. Bloqueamos.
    try:
        for tok in tokenize.generate_tokens(io.StringIO(nova.strip() + "\n").readline):
            if tok.type == tokenize.COMMENT:
                return Veredito(False, "comentario_bloqueado",
                                "comentários não são permitidos em mutações (vetor de prompt injection)"), ""
            if tok.type == tokenize.STRING and len(tok.string) > 20:
                return Veredito(False, "string_bloqueada",
                                "strings longas não são permitidas em mutações (vetor de prompt injection)"), ""
    except tokenize.TokenError:
        pass

    linhas[numero_linha - 1] = nova
    mutado = "\n".join(linhas) + "\n"
    try:
        arvore = ast.parse(mutado)
    except SyntaxError as e:
        return Veredito(False, "erro_sintaxe", f"código mutado não compila: {e.msg} (linha {e.lineno})"), ""
    if any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(arvore)):
        return Veredito(False, "import_bloqueado", "mutações não podem importar módulos"), ""
    problema = _checar_nomes(arvore)
    if problema:
        return Veredito(False, "codigo_perigoso", problema), ""
    return Veredito(True, "ok", f"linha {numero_linha}: '{antiga.strip()}' -> '{nova.strip()}'"), mutado


def validar_teste(codigo_teste: str) -> Veredito:
    try:
        arvore = ast.parse(codigo_teste)
    except SyntaxError as e:
        return Veredito(False, "erro_sintaxe", f"teste não compila: {e.msg} (linha {e.lineno})")
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for a in no.names:
                if a.name.split(".")[0] not in IMPORTS_PERMITIDOS_TESTE:
                    return Veredito(False, "import_bloqueado", f"import proibido: {a.name}")
        if isinstance(no, ast.ImportFrom):
            if (no.module or "").split(".")[0] not in IMPORTS_PERMITIDOS_TESTE:
                return Veredito(False, "import_bloqueado", f"import proibido: {no.module}")
    problema = _checar_nomes(arvore)
    if problema:
        return Veredito(False, "codigo_perigoso", problema)
    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test") for n in arvore.body):
        return Veredito(False, "sem_teste", "defina ao menos uma função 'test_...' no nível do módulo")
    return Veredito(True, "ok")


# --------------------------------------------------------------- execução

def _ambiente_limpo() -> dict[str, str]:
    """Só o mínimo para o Python rodar. Nenhuma credencial chega à sandbox."""
    manter = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "WINDIR")
    env = {k: v for k, v in os.environ.items() if k.upper() in manter}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def rodar_pytest(codigo_alvo: str, testes: dict[str, str], extra: list[str] | None = None) -> tuple[bool, str]:
    """Roda os testes contra `codigo_alvo` numa pasta temporária isolada."""
    with tempfile.TemporaryDirectory(prefix="arena_") as pasta:
        p = Path(pasta)
        (p / "descontos.py").write_text(codigo_alvo, encoding="utf-8")
        for nome, codigo in testes.items():
            (p / nome).write_text(codigo, encoding="utf-8")
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                 "-o", "console_output_style=classic", "--tb=line", *(extra or []), *testes.keys()],
                cwd=pasta, env=_ambiente_limpo(), capture_output=True, text=True, stdin=subprocess.DEVNULL,
                encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT: testes excederam o limite de tempo"
        saida = (r.stdout + r.stderr).strip()
        return r.returncode == 0, saida[-1500:]


def funcoes_de_teste(codigo_teste: str) -> list[str]:
    return [n.name for n in ast.parse(codigo_teste).body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]


def testes_que_falham(codigo_alvo: str, nome_arquivo: str, codigo_teste: str) -> tuple[set[str], str]:
    """Nomes das funções de teste que falham contra `codigo_alvo`."""
    todas = set(funcoes_de_teste(codigo_teste))
    passou, saida = rodar_pytest(codigo_alvo, {nome_arquivo: codigo_teste}, extra=["-rf"])
    if passou:
        return set(), saida
    falhas = set(re.findall(r"FAILED \S+?::(\w+)", saida)) & todas
    return (falhas or todas), saida  # erro de coleta/importação: todas contam como falha


def remover_funcoes(codigo_teste: str, nomes: set[str]) -> str:
    arvore = ast.parse(codigo_teste)
    arvore.body = [n for n in arvore.body if not (isinstance(n, ast.FunctionDef) and n.name in nomes)]
    return ast.unparse(arvore) + "\n"


ORACULO = r'''
import random, importlib.util, json, sys
def carregar(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
a = carregar("orig", "orig.py"); b = carregar("mut", "mut.py")
rnd = random.Random(1234)
UFS = ["GO", "DF", "SP", "MG", ""]
CUPONS = [None, "PRIMEIRA10", "MENOS20", "XYZ", "primeira10"]
QTDS = [0, 1, 49, 50, 51, 99, 100, 101, 150]
VALORES = [0.0, 19.99, 20.0, 99.99, 100.0, 100.01, 299.99, 300.0, 300.01, 1000.0]
def itens_aleatorios():
    return [{"preco": round(rnd.uniform(0.5, 60), 2), "quantidade": rnd.choice(QTDS + [rnd.randint(0, 120)])}
            for _ in range(rnd.randint(0, 4))]
casos = []
for q in QTDS + [rnd.randint(0, 200) for _ in range(200)]:
    casos.append(("desconto_volume", (q,)))
for v in VALORES + [round(rnd.uniform(0, 500), 2) for _ in range(300)]:
    for c in CUPONS: casos.append(("aplicar_cupom", (v, c)))
    for u in UFS: casos.append(("frete", (v, u)))
for _ in range(1500):
    it = itens_aleatorios()
    casos.append(("subtotal", (it,)))
    casos.append(("total_pedido", (it, rnd.choice(UFS), rnd.choice(CUPONS))))
def chamar(m, f, args):
    try: return ("ok", getattr(m, f)(*args))
    except Exception as e: return ("erro", type(e).__name__)
for f, args in casos:
    ra, rb = chamar(a, f, args), chamar(b, f, args)
    if ra != rb:
        print(json.dumps({"diferente": True, "funcao": f, "entrada": repr(args), "original": repr(ra), "mutante": repr(rb)}))
        sys.exit(0)
print(json.dumps({"diferente": False, "casos": len(casos)}))
'''


def oraculo_diferencial(original: str, mutado: str) -> tuple[bool, str]:
    """True se o mutante MUDA o comportamento (não é equivalente)."""
    import json
    with tempfile.TemporaryDirectory(prefix="oraculo_") as pasta:
        p = Path(pasta)
        (p / "orig.py").write_text(original, encoding="utf-8")
        (p / "mut.py").write_text(mutado, encoding="utf-8")
        (p / "oraculo.py").write_text(ORACULO, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, "oraculo.py"], cwd=pasta, env=_ambiente_limpo(),
                               capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return True, "timeout no oráculo (mutante provavelmente causa loop)"
        try:
            dados = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            return True, f"oráculo falhou ao executar: {r.stderr[-300:]}"
        if dados["diferente"]:
            return True, f"{dados['funcao']}{dados['entrada']}: original={dados['original']} mutante={dados['mutante']}"
        return False, f"nenhuma diferença em {dados['casos']} casos"
