"""Painel visual da Arena (localhost).

    python painel.py            → abre http://localhost:8000

- Partida AO VIVO: roda os agentes locais e transmite cada evento por SSE.
- REPLAY: reproduz uma partida gravada (logs/*/eventos.jsonl ou exemplos/*),
  útil como plano B na apresentação.
Funciona 100% offline (sem CDN, sem fontes externas).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
import webbrowser
from pathlib import Path

import ollama
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import arbitro
import arena
import progresso

RAIZ = Path(__file__).parent
WEB = RAIZ / "painel"


class Transmissao:
    """Guarda os eventos da sessão atual e entrega a qualquer navegador conectado
    (quem chega atrasado ou recarrega a página recebe tudo desde o início)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.eventos: list[dict] = []
        self.sessao = 0
        self.ativa = False
        self.parar = threading.Event()
        self.thread: threading.Thread | None = None

    def nova_sessao(self, modo: str, **info) -> int:
        with self.lock:
            self.sessao += 1
            self.eventos = []
            self.ativa = True
            self.parar = threading.Event()
        self.emitir({"ts": time.time(), "tipo": "sessao_inicio", "modo": modo, **info})
        return self.sessao

    def emitir(self, ev: dict):
        with self.lock:
            self.eventos.append(ev)

    def encerrar(self):
        with self.lock:
            self.ativa = False
        self.emitir({"ts": time.time(), "tipo": "sessao_fim"})


tx = Transmissao()
app = FastAPI(title="Arena Mutante vs. Caçador")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.middleware("http")
async def sem_cache(request, chamar):
    # Na apresentação, nunca servir CSS/JS velhos do cache do navegador.
    resposta = await chamar(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        resposta.headers["Cache-Control"] = "no-store"
    return resposta


# ------------------------------------------------------------------ páginas

@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/config")
def config():
    codigo = (RAIZ / "campo" / "descontos.py").read_text(encoding="utf-8")
    try:
        modelos = sorted(m.model for m in ollama.list().models)
    except Exception:
        modelos = []
    return {
        "codigo": codigo.splitlines(),
        "editaveis": sorted(arbitro.linhas_editaveis(codigo)),
        "testes_base": (RAIZ / "campo" / "test_base.py").read_text(encoding="utf-8"),
        "modelos": modelos,
        "gravacoes": listar_gravacoes(),
        "progresso": progresso.situacao(),
        "ativa": tx.ativa,
    }


def listar_gravacoes() -> list[dict]:
    itens = []
    for base in ("exemplos", "logs"):
        for arq in sorted((RAIZ / base).glob("*/eventos.jsonl"), reverse=True):
            resumo_arq = arq.parent / "resumo.json"
            resumo = json.loads(resumo_arq.read_text(encoding="utf-8")) if resumo_arq.exists() else {}
            if not resumo:
                continue  # partida incompleta
            itens.append({
                "id": f"{base}/{arq.parent.name}",
                "nome": arq.parent.name,
                "origem": base,
                "placar": resumo.get("placar"),
                "rodadas": resumo.get("rodadas"),
                "duracao_s": resumo.get("duracao_s"),
                "modelos": {p: a.get("modelo") for p, a in resumo.get("agentes", {}).items()},
            })
    return itens


# ------------------------------------------------------------------ controle

class PedidoPartida(BaseModel):
    rodadas: int = 2
    modelo_mutante: str = "qwen2.5-coder:7b"
    modelo_cacador: str = "qwen2.5-coder:7b"
    tentativas: int = 3
    max_passos: int = 12
    evoluir_defesa: bool = True  # a defesa herda os testes vencedores de partidas anteriores
    evoluir_ataque: bool = True  # o Mutante usa a memória de ataques de partidas anteriores


class PedidoReplay(BaseModel):
    id: str
    velocidade: float = 1.0


def _ocupado():
    if tx.ativa and tx.thread and tx.thread.is_alive():
        raise HTTPException(409, "Já existe uma partida em andamento. Pare-a primeiro.")


@app.post("/api/partida")
def iniciar_partida(p: PedidoPartida):
    _ocupado()
    args = arena.criar_parser().parse_args([])
    args.rodadas = max(1, min(p.rodadas, 10))
    args.modelo_mutante, args.modelo_cacador = p.modelo_mutante, p.modelo_cacador
    args.tentativas, args.max_passos = p.tentativas, p.max_passos
    args.sem_evolucao_defesa = not p.evoluir_defesa
    args.sem_evolucao_ataque = not p.evoluir_ataque
    tx.nova_sessao("ao_vivo", modelos={"mutante": p.modelo_mutante, "cacador": p.modelo_cacador})
    parar = tx.parar

    def rodar():
        try:
            asyncio.run(arena.partida(args, emitir=tx.emitir, parar=parar))
        except Exception as e:  # mostra o erro no painel em vez de morrer calado
            tx.emitir({"ts": time.time(), "tipo": "erro", "mensagem": f"{type(e).__name__}: {e}"})
        finally:
            tx.encerrar()

    tx.thread = threading.Thread(target=rodar, daemon=True)
    tx.thread.start()
    return {"ok": True, "sessao": tx.sessao}


@app.post("/api/replay")
def iniciar_replay(p: PedidoReplay):
    _ocupado()
    arq = (RAIZ / p.id / "eventos.jsonl").resolve()
    if RAIZ.resolve() not in arq.parents or not arq.exists():
        raise HTTPException(404, "gravação não encontrada")
    eventos = [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]
    velocidade = max(0.25, min(p.velocidade, 20))
    tx.nova_sessao("replay", gravacao=p.id, velocidade=velocidade)
    parar = tx.parar

    def rodar():
        anterior = eventos[0]["ts"] if eventos else 0
        for ev in eventos:
            if parar.is_set():
                tx.emitir({"ts": time.time(), "tipo": "interrompida"})
                break
            espera = min(max(ev["ts"] - anterior, 0), 3.0) / velocidade  # pausas longas são encurtadas
            anterior = ev["ts"]
            if espera > 0:
                parar.wait(espera)
            tx.emitir({**ev, "ts": time.time()})
        tx.encerrar()

    tx.thread = threading.Thread(target=rodar, daemon=True)
    tx.thread.start()
    return {"ok": True, "sessao": tx.sessao}


@app.post("/api/progresso/zerar")
def zerar_progresso():
    _ocupado()
    return {"ok": True, "removidos": progresso.zerar(), "progresso": progresso.situacao()}


@app.post("/api/parar")
def parar():
    tx.parar.set()
    return {"ok": True}


@app.get("/api/eventos")
async def eventos():
    async def fluxo():
        sessao, i = None, 0
        ultimo_ping = time.time()
        while True:
            with tx.lock:
                if tx.sessao != sessao:
                    sessao, i = tx.sessao, 0
                novos = tx.eventos[i:]
                i += len(novos)
            for ev in novos:
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            if not novos and time.time() - ultimo_ping > 15:
                ultimo_ping = time.time()
                yield ": ping\n\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(fluxo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/estado")
def estado():
    return JSONResponse({"ativa": tx.ativa, "sessao": tx.sessao, "eventos": len(tx.eventos)})


def main():
    ap = argparse.ArgumentParser(description="Painel visual da Arena")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--sem-navegador", action="store_true")
    a = ap.parse_args()
    url = f"http://localhost:{a.porta}"
    print(f"\n  🏟  Arena Mutante vs. Caçador → {url}\n")
    if not a.sem_navegador:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.porta, log_level="warning")


if __name__ == "__main__":
    main()
