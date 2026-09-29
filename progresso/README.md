# Progresso: quem evolui mais, o ataque ou a defesa?

Esta pasta guarda o que **evolui entre partidas**. É criada e atualizada automaticamente por [`progresso.py`](../progresso.py).

| Caminho | Lado | O que é |
|---|---|---|
| `suite/test_001.py`, `test_002.py`, ... | 🛡️ Defesa (Caçador) | Um teste do Caçador que **matou um mutante**. Na próxima partida, faz parte da suíte que o Mutante precisa enganar. O cabeçalho diz de qual partida e rodada ele veio |
| `arsenal.json` | ⚔️ Ataque (Mutante) | **Memória de ataques**: cada mutação tentada e o resultado (sobreviveu, abatida, detectada pela suíte, equivalente ou erro). O Mutante recebe esse resumo no início de cada turno |
| `historico.json` | ambos | Uma entrada por partida: data, modelos, placar e o nível de cada lado no início e no fim |

## Níveis (mesma régua para os dois lados)

| Nível | Fórmula | Sobe quando... |
|---|---|---|
| 🛡️ **Defesa** | 1 + mutantes abatidos (testes em `suite/`) | o Caçador **vence** uma rodada |
| ⚔️ **Ataque** | 1 + brechas descobertas (mutações distintas que sobreviveram) | o Mutante **vence** uma rodada com um ataque novo |

Cada lado só sobe quando vence. Por isso dá para comparar quem evolui mais. A memória do Mutante também guarda os fracassos, porque eles o ajudam a não repetir erros, mas **só as vitórias contam para o nível**.

## Detalhes

- Os testes da defesa já foram filtrados pelo árbitro: todos passam no código correto (nenhuma alucinação entra aqui).
- A primeira linha de cada teste tem uma assinatura `[sha:...]` do conteúdo, usada para não salvar o mesmo teste duas vezes.
- Cada lado pode ser ligado ou desligado separadamente: caixas de seleção no painel, ou `--sem-evolucao-defesa` / `--sem-evolucao-ataque` no terminal.
- Para recomeçar do nível 1: botão **↺ zerar** no painel ou `python arena.py --zerar-progresso`.
