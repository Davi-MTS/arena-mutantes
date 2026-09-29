# Roteiro da apresentação (15 min)

## Antes de começar (5 min antes)
1. Conecte o notebook ao projetor e **desligue o Wi-Fi**: a demo é 100% local, e isso vira argumento.
2. Dê dois cliques em `iniciar_painel.bat`. Ele pré-carrega o modelo na GPU e abre `http://localhost:8000`.
3. Aperte **F** para tela cheia.
4. Deixe a janela inicial aberta, com 2 rodadas e `qwen2.5-coder:7b` nos dois lados.

## Roteiro

| Tempo | O que falar | O que mostrar |
|---|---|---|
| 0:00–2:00 | **Problema:** agentes de IA já escrevem código e testes, mas alucinam. Como confiar numa IA autônoma? **Nossa resposta:** não confiar na palavra dela, e sim verificar executando. | Tela inicial do painel |
| 2:00–4:00 | **A ideia:** um jogo adversarial (autojogo). O Mutante insere um bug sutil e o Caçador escreve testes para matá-lo. Quem decide é um árbitro determinístico, não uma IA. | Aperte **C** (Como funciona) |
| 4:00–6:00 | **Arquitetura:** MCP como fronteira (os agentes só agem por ferramentas padronizadas); regras impostas no servidor; LLM local via Ollama (Qwen2.5-Coder 7B, 4 bits, GTX 1660 Super, ~24 tokens/s). | Diagrama do "Como funciona" |
| 6:00–11:00 | **Demo ao vivo:** clique em *Iniciar partida*. Narre: a mente do agente (streaming), as ferramentas MCP acendendo, a trilha do árbitro, o bug aparecendo no código com a prova do oráculo, os testes marcados como válidos ou alucinados. | Painel ao vivo |
| 11:00–13:00 | **Resultados e segurança:** tela final; alucinações barradas; tool calls via texto (fallback); anti prompt-injection entre agentes; sandbox; ambiente sem credenciais; limites de autonomia. | Tela final + README |
| 13:00–15:00 | **Limitações e futuro:** modelo pequeno não aprende bem com o feedback; o Qwen3 4B "pensou" 2 min sem agir; o design da ferramenta importa (edição por substituição). Futuro: Arena completa com torneio e Elo. | Perguntas |

## Plano B
Se a partida ao vivo travar ou demorar: **Nova partida → Replay de partida gravada → 4×**. A plateia vê a mesma coisa, só que gravada.

## Frases de efeito
- "O prompt é uma sugestão; o servidor MCP é a lei."
- "A IA pode alucinar; o pytest não."
- "Testes que falham no código correto são alucinações, e o árbitro joga fora sozinho."
- "Tudo isso rodando numa placa de vídeo de 6 GB, sem internet e sem pagar API."
