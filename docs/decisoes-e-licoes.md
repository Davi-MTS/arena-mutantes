# Decisões de projeto e lições aprendidas

## Decisões de projeto

| Decisão | Por quê |
|---|---|
| **Árbitro por execução, não por LLM** | Se uma IA julgasse a outra, o juiz também poderia alucinar. Pytest e oráculo diferencial são objetivos e reprodutíveis. |
| **MCP como fronteira** | O agente só age sobre o mundo por ferramentas padronizadas e auditáveis. Trocar o modelo não exige mudar o servidor. |
| **Regras impostas no servidor** | Se o prompt for ignorado ou manipulado, o servidor ainda recusa jogadas fora do turno. |
| **Oráculo diferencial** | Rejeita mutantes equivalentes, que não mudam o comportamento e seriam impossíveis de matar. |
| **Filtro de alucinação por função de teste** | Um `assert` com valor inventado é descartado sem invalidar os testes corretos do mesmo envio. |
| **Edição por substituição (`trecho_original` → `trecho_novo`), ancorada pelo conteúdo** | Pedindo a linha inteira, o modelo errava indentação e estrutura (trocava um `if` por um `return`) e errava o número da linha por ±1. Com a interface no estilo `str_replace` dos agentes de código profissionais, ele só decide *o que* trocar. |
| **Parser de reserva para tool calls** | O Qwen2.5-Coder 7B escreve a chamada como JSON no texto em vez de usar o formato nativo do Ollama. |
| **Streaming + eventos** | O painel mostra o modelo "pensando" token a token. Os mesmos eventos, gravados, alimentam o replay. |
| **Modelos locais quantizados (Q4)** | Custo zero, privacidade (o código não sai da máquina) e funcionamento sem internet. Roda numa GTX 1660 Super de 6 GB. |
| **SDK MCP fixado em `<2`** | A versão 2 do SDK renomeou APIs (`FastMCP` virou `MCPServer`). A 1.x é estável para a entrega. |
| **Front-end sem dependências externas** | A demo funciona com o Wi-Fi desligado: sem CDN e sem fontes externas. |

## Evolução durante o desenvolvimento

Cada problema abaixo apareceu em partidas reais e levou a uma mudança no código:

| Problema observado | Correção |
|---|---|
| O modelo nunca usava o formato nativo de tool calling | Parser de reserva que extrai o JSON do texto |
| O modelo mandava 3 chamadas numa resposta só e o sistema executava só a primeira: o agente ficava preso relendo o código até estourar o limite | Executar até 4 chamadas em ordem |
| Contexto crescendo com releituras: cada passo foi de ~4 s para ~48 s (o modelo transbordou da VRAM para a CPU) | Releitura idêntica não é repetida no histórico |
| Um único `assert` alucinado invalidava um arquivo inteiro de testes corretos | Filtro de alucinação função por função |
| O Mutante errava a estrutura da linha e o número da linha | Ferramenta de edição por substituição, ancorada pelo conteúdo |
| O Caçador reenviava os mesmos 26 testes, ~90 s por tentativa | Pedido de 4 a 8 testes, teto de tokens e temperatura maior após erro |
| Com teto de tokens baixo demais, o JSON do Caçador vinha cortado | Teto maior para o Caçador e aviso específico de "chamada cortada" |
| O modelo escapava o JSON duas vezes (`\\n` literais no código) | Normalização da entrada no servidor, registrada em log |
| A saída do pytest expunha o caminho com o nome do usuário do sistema | Caminho trocado por `<sandbox>` |

## Lições sobre modelos locais (para o relatório)

1. **O desenho da ferramenta importa tanto quanto o modelo.** A mesma IA passou de "quase nunca consegue jogar" para "acerta de primeira" só mudando a interface da ferramenta.
2. **Tool calling em modelos pequenos é frágil.** Sem o parser de reserva, o agente simplesmente não funcionaria.
3. **Alucinação de expectativa é a regra, não a exceção.** Em várias partidas, mais da metade das funções de teste do Caçador tinha valores esperados inventados.
4. **Modelos de 7B não aprendem bem com o feedback.** Repetem o mesmo erro mesmo recebendo a explicação e a linha original.
5. **"Pensar" não é agir.** O Qwen3 4B raciocinou em texto por mais de 2 minutos sem fazer nenhuma jogada. Limites de autonomia (passos e tokens) são obrigatórios.
6. **Contexto é custo.** Com 6 GB de VRAM, cada token extra no histórico deixa o agente mais lento.
7. **Verificação por execução resolve o problema de confiança.** Não é preciso confiar no agente quando cada afirmação dele é checada executando código.

## Trabalhos futuros

- **Arena completa:** torneio entre vários modelos com rating Elo.
- Novos jogos: Fuzzer vs. Validador, Código trapaceiro vs. Revisor, Arena de *prompt injection*.
- Sandbox em container sem rede ou WebAssembly.
- Transporte MCP via HTTP com autenticação OAuth 2.1, para agentes remotos.
