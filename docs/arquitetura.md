# Arquitetura

Este documento explica **como as peças se conectam**. Para rodar o projeto, veja o [README](../README.md).

## Visão geral

```
            ┌───────────────────────── Navegador (localhost:8000) ─────────────────────────┐
            │  painel/index.html · estilo.css · app.js  (placar, mentes, código, árbitro)  │
            └───────────────────────────────▲──────────────────────────────────────────────┘
                                            │ Server-Sent Events (1 evento por acontecimento)
┌───────────────────────────────────────────┴─────────────────────────────────────────────────┐
│ painel.py (FastAPI)          ao vivo: roda arena.partida() numa thread · replay: relê gravação │
└───────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                            │ chama
┌───────────────────────────────────────────▼─────────────────────────────────────────────────┐
│ arena.py (orquestrador + agentes = CLIENTE MCP)                                             │
│                                                                                             │
│   🧟 Agente Mutante ──► Ollama (qwen2.5-coder:7b) ◄── 🏹 Agente Caçador                      │
│   cada agente recebe SÓ as ferramentas do seu papel (lista de permissões)                   │
│   logs/<partida>/agentes.jsonl · eventos.jsonl                                              │
└───────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                            │ MCP · JSON-RPC via stdio (subprocesso)
┌───────────────────────────────────────────▼─────────────────────────────────────────────────┐
│ servidor_arena.py (SERVIDOR MCP)                                                            │
│   ferramentas dos agentes: ler_codigo · ler_testes · propor_mutacao · enviar_teste          │
│   ferramentas do orquestrador: admin_nova_rodada · admin_abrir_turno_cacador · ...          │
│   estado do jogo e regras de turno impostas AQUI (não no prompt)                            │
│                                            │                                                │
│                              arbitro.py (ÁRBITRO DETERMINÍSTICO)                            │
│   validação AST · oráculo diferencial · sandbox pytest · filtro de alucinação               │
│   logs/<partida>/arbitro.jsonl                                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                     campo/descontos.py (código em disputa) · campo/test_base.py
```

## Os arquivos e o papel de cada um

| Arquivo | Papel | Tecnologia |
|---|---|---|
| [`arena.py`](../arena.py) | Orquestra a partida e implementa os dois agentes: conversa com o LLM, extrai as chamadas de ferramenta e as executa via MCP | Ollama (streaming), cliente MCP |
| [`servidor_arena.py`](../servidor_arena.py) | Servidor MCP: expõe as ferramentas, guarda o estado do jogo e impõe as regras | MCP Python SDK (`FastMCP`, stdio) |
| [`arbitro.py`](../arbitro.py) | Decide cada jogada executando código, sem IA | `ast`, `subprocess`, `pytest` |
| [`progresso.py`](../progresso.py) | Evolução entre partidas: testes herdados da defesa (`progresso/suite/`), memória de ataques do Mutante (`progresso/arsenal.json`), níveis e histórico | Python (arquivos JSON) |
| [`painel.py`](../painel.py) | Servidor web do painel: partida ao vivo e replay | FastAPI, SSE |
| [`painel/`](../painel/) | Interface visual | HTML, CSS e JavaScript puros (sem CDN) |
| [`campo/descontos.py`](../campo/descontos.py) | Código em disputa: regras de preço de uma distribuidora. **As docstrings são a especificação** | Python |
| [`campo/test_base.py`](../campo/test_base.py) | Suíte inicial, propositalmente fraca | pytest |

## Fluxo de uma rodada

```
 orquestrador            Mutante (LLM)              servidor MCP / árbitro             Caçador (LLM)
     │ admin_nova_rodada ───────────────────────────────►│ código volta ao original
     │──── turno ───────────►│                           │
     │                       │ ler_codigo, ler_testes ──►│
     │                       │ propor_mutacao(linha, trecho_original, trecho_novo)
     │                       │──────────────────────────►│ 1. acha o trecho (ancoragem por conteúdo)
     │                       │                           │ 2. valida AST (sintaxe, linha editável, sem comentários)
     │                       │                           │ 3. oráculo: original ≠ mutante? (~5 mil entradas)
     │                       │                           │ 4. suíte atual passa no mutante? → mutante VIVO
     │ admin_abrir_turno_cacador ───────────────────────►│
     │──── turno ─────────────────────────────────────────────────────────────────────►│
     │                                                   │◄── ler_codigo (código COM bug) │
     │                                                   │◄── enviar_teste(codigo) ───────│
     │                                                   │ 1. valida AST (imports/nomes proibidos)
     │                                                   │ 2. roda cada teste no código CORRETO:
     │                                                   │    os que falham = ALUCINAÇÃO → descartados
     │                                                   │ 3. roda os válidos no MUTANTE: algum falha? → ABATIDO
     │ admin_estado → placar, vencedor da rodada         │   testes vencedores entram na suíte
```

Cada lado tem no máximo `--tentativas` jogadas (3) e `--max-passos` chamadas ao LLM (12) por turno. Esgotou, perde a rodada.

## Evolução entre partidas (ataque × defesa)

```
 🛡️ DEFESA   suíte = test_base.py + progresso/suite/test_NNN.py (herdados)
             Caçador mata um mutante  → teste válido salvo em progresso/suite/test_NNN.py
             nível da defesa = 1 + testes herdados

 ⚔️ ATAQUE   toda mutação tentada     → lição em progresso/arsenal.json (sobreviveu / abatido /
                                         detectado pela suíte / equivalente / erro)
             início de cada turno     → o Mutante recebe a memória agrupada por resultado
             nível do ataque = 1 + mutações distintas que já sobreviveram

 fim da partida → progresso/historico.json += {placar, ataque início→fim, defesa início→fim}
```

- **Mesma régua:** cada lado só sobe de nível quando vence uma rodada, para dar para comparar quem evolui mais.
- O servidor MCP lê as variáveis `ARENA_EVOLUI_DEFESA`, `ARENA_EVOLUI_ATAQUE` (cada lado liga/desliga) e `ARENA_PARTIDA`, definidas por `arena.py`.
- Onde cada coisa é gravada: o destino do mutante (sobreviveu ou abatido) em `_encerrar`; as rejeições em `propor_mutacao`; os testes vencedores em `enviar_teste`.
- Duplicatas de teste são evitadas por uma assinatura SHA-256 do conteúdo, gravada no cabeçalho de cada arquivo.
- Se a suíte passar de ~3.500 caracteres, `ler_testes` devolve só as asserções distintas (até 60), para caber no contexto de 6k tokens do modelo. A memória do Mutante mostra no máximo 6 ataques por grupo, pelo mesmo motivo.
- **Os pesos do LLM continuam os mesmos:** evoluem a suíte (defesa) e a memória no prompt (ataque).

## Ferramentas MCP

| Ferramenta | Quem usa | O que faz |
|---|---|---|
| `ler_codigo()` | ambos | Devolve `descontos.py` numerado. Para o Mutante, lista também as linhas editáveis |
| `ler_testes()` | ambos | Devolve a suíte atual (base + testes vencedores) |
| `propor_mutacao(numero_linha, trecho_original, trecho_novo, justificativa)` | Mutante | Edição por substituição, ex.: na linha 15 trocar `>=` por `>` |
| `enviar_teste(codigo, justificativa)` | Caçador | Arquivo pytest que deve passar no código correto e falhar no mutante |
| `admin_nova_rodada()` | só o orquestrador | Restaura o código e abre o turno do Mutante |
| `admin_abrir_turno_cacador()` | só o orquestrador | Passa a vez se houver mutante vivo |
| `admin_encerrar_por_limite()` | só o orquestrador | Encerra o turno de quem estourou o limite de passos |
| `admin_estado()` | só o orquestrador | Placar e gabarito da rodada |

As ferramentas `admin_*` existem no servidor, mas **nunca são oferecidas ao LLM**: o cliente filtra por papel e o servidor confere de quem é o turno.

## Como o agente funciona (laço agêntico)

1. Monta a conversa: prompt do papel + tarefa.
2. Chama o Ollama **em streaming**; os pedaços de texto vão para o painel em tempo real.
3. Extrai as chamadas de ferramenta:
   - no **formato nativo** do Ollama, se existir;
   - senão, pelo **parser de reserva**, que procura objetos `{"name": ..., "arguments": ...}` no texto (o Qwen2.5-Coder 7B sempre responde assim).
4. Executa até 4 chamadas em ordem via MCP e devolve os resultados ao modelo.
5. Repete até o servidor responder `turno_encerrado: true` ou até o limite de passos.

Otimizações para modelos pequenos:
- releituras idênticas não são repetidas no contexto;
- teto de tokens por resposta;
- temperatura sobe após uma jogada rejeitada, para a nova tentativa não repetir a anterior.

## Eventos do painel

`arena.py` emite eventos (também gravados em `eventos.jsonl`, que alimenta o replay):

| Evento | Quando |
|---|---|
| `partida_inicio`, `carregando`, `mcp_conectado` | início da partida |
| `rodada_inicio`, `turno` | começo de rodada ou de turno |
| `pensando`, `llm_delta`, `llm_fim` | o LLM está gerando (streaming) e terminou (tokens, tok/s, tempo) |
| `ferramenta`, `resultado` | chamada MCP e resposta do servidor |
| `mutante_vivo` | gabarito: linha original, nova linha, prova do oráculo |
| `sem_ferramenta`, `bloqueio`, `limite` | erros de protocolo, ferramenta proibida, limite de autonomia |
| `progresso` | níveis de ataque e defesa e testes herdados no início da partida |
| `memoria` | memória de ataques entregue ao Mutante no início do turno |
| `rodada_fim`, `partida_fim` | placar e resumo final |

## Logs gerados por partida (`logs/<data_hora>/`)

| Arquivo | Conteúdo |
|---|---|
| `agentes.jsonl` | Cada resposta do LLM (texto, chamadas extraídas, origem nativa ou texto, tokens, tok/s, tempo) e cada chamada ou resultado de ferramenta |
| `arbitro.jsonl` | Cada veredito com evidências: mutação aceita ou rejeitada e o motivo, prova do oráculo, testes alucinados, saída do pytest |
| `eventos.jsonl` | Linha do tempo completa para o replay do painel |
| `resumo.json` | Placar, métricas por agente, erros barrados pelo árbitro, mutações que nasceram |
