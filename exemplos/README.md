# Partidas gravadas

Logs completos de partidas reais, sem edição. Servem como evidência das decisões dos agentes (entregável "b" da Proposta 1) e podem ser assistidos no painel.

## Como assistir
```bash
python painel.py
```
Na tela inicial: **Replay de partida gravada → `partida_exemplo` → velocidade → Assistir replay**.

## `partida_exemplo/`
**Configuração:** Qwen2.5-Coder 7B (Q4) nos dois lados · GTX 1660 Super 6 GB · ~22 tokens/s · 3 rodadas · 147 s

**Placar final: 🧟 Mutante 1 × 2 🏹 Caçador**

| Rodada | O que aconteceu | Vencedor |
|---|---|---|
| 1 | O Mutante mudou o frete do DF de `25.0` para `24.99`, um bug de 1 centavo. O Caçador enviou testes em 3 tentativas: numa, os testes válidos não detectaram o bug; nas outras duas, **todos os testes eram alucinados** (valores esperados inventados) e foram descartados pelo árbitro | 🧟 Mutante |
| 2 | O Mutante tentou trocar `base` por `com_volume` e por `subtotal`, mas **a suíte atual já detectava** esses bugs. Na última tentativa, o trecho `base` aparecia em várias linhas próximas (trecho ambíguo) | 🏹 Caçador |
| 3 | O Mutante insistiu três vezes no mesmo trecho ambíguo (`base`) sem aproveitar o feedback | 🏹 Caçador |

**Números:**
- 11 chamadas ao LLM do Mutante e 6 do Caçador;
- **0 tool calls no formato nativo**: todas vieram como JSON no texto;
- **8 funções de teste alucinadas** barradas pelo árbitro.

## Arquivos de cada partida

| Arquivo | Conteúdo |
|---|---|
| `agentes.jsonl` | Cada resposta do LLM (texto completo, chamadas extraídas, tokens, tokens/s, tempo) e cada chamada de ferramenta com o resultado |
| `arbitro.jsonl` | Cada veredito do árbitro com evidências: mutação aceita ou rejeitada e o motivo, prova do oráculo, testes alucinados, saída do pytest |
| `eventos.jsonl` | Linha do tempo completa usada pelo Replay do painel |
| `resumo.json` | Placar, métricas por agente e erros barrados pelo árbitro |

Cada linha dos `.jsonl` é um objeto JSON independente, fácil de analisar com Python ou pandas.
