# Arena de Agentes: Mutante vs. Caçador

> N2 – Tecnologias Emergentes (SENAI FATESG) · **Proposta 1: Arquitetura Orientada a Agentes Autônomos de Código e MCP**

Dois agentes autônomos de IA **jogam um contra o outro** sobre um código real:

- 🧟 **Mutante**: insere um bug sutil no código, tentando escapar dos testes existentes.
- 🏹 **Caçador**: lê o código e a especificação (docstrings) e escreve testes automatizados para "matar" o bug.

Quem decide cada jogada é um **árbitro determinístico que executa código** (pytest + oráculo diferencial), **nunca um LLM**. Cada teste que mata um mutante entra na suíte, que vai ficando mais forte a cada rodada (autojogo adversarial, no estilo *mutation testing*).

Tudo roda **100% local**: modelos abertos via **Ollama**, ferramentas expostas via **Model Context Protocol (MCP)**. Não usa API paga nem precisa de internet durante a execução.

---

## Arquitetura

```
┌────────────────────────── arena.py (orquestrador / cliente MCP) ──────────────────────────┐
│                                                                                           │
│  🧟 Agente Mutante ──┐       lista de permissões por papel          ┌── 🏹 Agente Caçador   │
│  (LLM local, Ollama) │  (cada agente só vê as ferramentas dele)     │  (LLM local, Ollama)  │
│                      ▼                                              ▼                     │
│              ler_codigo · ler_testes · propor_mutacao | enviar_teste                      │
│                                                                                           │
│  logs/<partida>/agentes.jsonl  ← cada resposta do LLM, chamada de ferramenta e resultado  │
└──────────────────────────────────────────┬────────────────────────────────────────────────┘
                                           │ MCP (JSON-RPC via stdio)
┌──────────────────────────────────────────▼────────────────────────────────────────────────┐
│ servidor_arena.py (servidor MCP)                                                          │
│   estado do jogo · regras de turno impostas no servidor · ferramentas admin_* (só do     │
│   orquestrador)                                                                           │
│                                   │                                                       │
│                    arbitro.py (árbitro determinístico)                                    │
│   ├─ validação estática (AST): linhas editáveis, imports/nomes proibidos, comentários     │
│   ├─ oráculo diferencial: original vs. mutante em ~5.000 entradas → rejeita equivalentes │
│   ├─ sandbox: pytest em subprocesso, pasta temporária, timeout, ambiente sem segredos     │
│   └─ filtro de alucinação: descarta testes que falham no código CORRETO                   │
│                                                                                           │
│  logs/<partida>/arbitro.jsonl ← veredito de cada jogada, com evidências                   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
          campo/descontos.py (código em disputa: regras de preço de uma distribuidora)
```

### Fluxo de uma rodada
1. O orquestrador chama `admin_nova_rodada` e o código volta ao original.
2. **Turno do Mutante**, com até N tentativas:
   1. `ler_codigo` e `ler_testes`;
   2. `propor_mutacao(linha, nova_linha, justificativa)`;
   3. o árbitro valida a sintaxe e as regras, prova com o oráculo que o comportamento mudou e roda a suíte. O mutante só "nasce" se **sobreviver** à suíte.
3. **Turno do Caçador**, com até N tentativas:
   1. `ler_codigo` mostra o código com bug; as docstrings são a especificação;
   2. `enviar_teste(codigo)`;
   3. o árbitro descarta as funções de teste que falham no código correto (alucinações) e verifica se as válidas falham no mutante.
4. Pontua quem venceu. Os testes que mataram o mutante entram na suíte da próxima rodada.

---

## Pré-requisitos
- Python 3.10+
- [Ollama](https://ollama.com) instalado e rodando
- GPU com ~6 GB de VRAM recomendada (também roda em CPU, mais devagar)

## Execução passo a passo
```bash
# 1. dependências Python
pip install -r requirements.txt

# 2. modelos locais (uma vez, precisa de internet só aqui)
ollama pull qwen2.5-coder:7b
ollama pull qwen3:4b

# 3. partida (funciona offline)
python arena.py --rodadas 3

# modelos diferentes em cada lado (duelo de modelos)
python arena.py --rodadas 3 --modelo-mutante qwen3:4b --modelo-cacador qwen2.5-coder:7b
```

| Opção | Padrão | Significado |
|---|---|---|
| `--rodadas` | 3 | número de rodadas |
| `--modelo` | `qwen2.5-coder:7b` | modelo dos dois agentes |
| `--modelo-mutante` / `--modelo-cacador` | – | modelo específico de cada lado |
| `--max-passos` | 12 | **limite de autonomia**: chamadas ao LLM por turno |
| `--tentativas` | 3 | jogadas por turno antes de perder a rodada |
| `--num-ctx` | 6144 | janela de contexto (ajuste à sua VRAM) |

## Saídas (logs estruturados)
Cada partida cria `logs/<data_hora>/` com:
- `agentes.jsonl`: cada resposta do LLM (texto, chamada extraída, tokens, tokens/s, tempo) e cada chamada ou resultado de ferramenta;
- `arbitro.jsonl`: cada veredito (mutação aceita ou rejeitada e o motivo, testes alucinados descartados, mutante morto, fim de rodada);
- `resumo.json`: placar, métricas por agente, contagem de erros e alucinações barrados.

### Partida de exemplo
[`exemplos/partida_3_rodadas/`](exemplos/partida_3_rodadas/) guarda os logs completos de uma partida real (Qwen2.5-Coder 7B nos dois lados, GTX 1660 Super, ~24 tokens/s, 252 s):

| Rodada | Bug inserido pelo Mutante | Resultado |
|---|---|---|
| 1 | frete de outra UF: `return 40.0` → expressão com variável inexistente | 🏹 Caçador matou (5 de 9 testes enviados eram alucinados e foram descartados) |
| 2 | tentou trocar o `if` por um `return` três vezes (erro de sintaxe repetido) | 🏹 Caçador (Mutante esgotou as tentativas) |
| 3 | desconto de 50 unidades: `0.05` → `0.1` | 🧟 Mutante sobreviveu (Caçador testou 49, não 50) |

**Placar: Caçador 2 × 1 Mutante.** Das 60 funções de teste enviadas em envios com alucinação, **26 tinham valor esperado inventado** e foram descartadas pelo árbitro.

---

## Decisões de projeto
| Decisão | Motivo |
|---|---|
| **Árbitro por execução, não por LLM** | LLMs alucinam. Pytest e oráculo diferencial são objetivos e reprodutíveis. |
| **MCP como fronteira** | O agente só age sobre o mundo por ferramentas padronizadas e auditáveis. Trocar o modelo não muda o servidor. |
| **Regras impostas no servidor** | Se o prompt for ignorado ou manipulado, o servidor ainda recusa jogadas fora do turno. |
| **Oráculo diferencial** | Rejeita mutantes equivalentes (que não mudam o comportamento e seriam impossíveis de matar). |
| **Filtro de alucinação por função de teste** | Um `assert` com expectativa inventada é descartado sem invalidar os testes corretos do mesmo envio. |
| **Parser de reserva para tool calls** | Modelos pequenos (ex.: Qwen2.5-Coder 7B) às vezes "escrevem" a chamada como JSON no texto em vez de usar o formato nativo. |
| **Modelos locais quantizados (Q4)** | Custo zero, privacidade, sem dependência de rede. Roda numa GTX 1660 Super (6 GB). |
| **SDK MCP fixado em `<2`** | A v2 do SDK renomeou APIs (`FastMCP` virou `MCPServer`). A v1 é estável para a entrega. |

## Segurança
| Ameaça | Mitigação |
|---|---|
| Código gerado por IA tentando fugir da sandbox ou ler segredos | Validação AST (sem `import os`, `open`, `eval`, `__import__`, `environ`...), subprocesso isolado, pasta temporária, timeout |
| Vazamento de credenciais | Servidor MCP e sandbox recebem só `PATH`/`SYSTEMROOT`/`TEMP`; nenhuma variável do usuário (tokens, chaves) é repassada |
| *Prompt injection* entre agentes (o Mutante escrever `# ignore as instruções...` no código que o Caçador vai ler) | Comentários e strings longas são proibidos em mutações |
| Agente usando ferramenta de outro papel ou do orquestrador | Lista de permissões por papel no cliente e checagem de turno no servidor. Ferramentas `admin_*` nunca são expostas ao LLM |
| Autonomia sem limite (loops, custo) | `--max-passos` por turno e `--tentativas` por jogada, com timeout em toda execução |
| Caçador usando o código correto como oráculo | Quando um teste falha no original, o árbitro **não** revela o valor esperado |

## Estrutura
```
arena-mutantes/
├── arena.py            # orquestrador + agentes (cliente MCP + Ollama)
├── servidor_arena.py   # servidor MCP com as ferramentas e regras do jogo
├── arbitro.py          # validação, sandbox, oráculo diferencial, filtro de alucinação
├── campo/
│   ├── descontos.py    # código em disputa
│   └── test_base.py    # suíte inicial (propositalmente fraca)
├── logs/               # gerado a cada partida
└── requirements.txt
```

## Trabalhos futuros
- **Arena completa**: torneio entre vários modelos com rating Elo.
- Novos jogos: Fuzzer vs. Validador, Código trapaceiro vs. Revisor, Arena de *prompt injection*.
- Painel web para acompanhar as partidas ao vivo.
