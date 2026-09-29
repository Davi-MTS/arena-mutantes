# Próximo passo: Laboratório de estratégias de caça

> **Status:** ideia aprovada, **ainda não implementada**. Este documento é o plano completo para continuar o trabalho (por uma pessoa ou por uma sessão do Claude Code) em qualquer computador.

## Por que fazer isso

Hoje a Arena mostra agentes competindo, mas a "evolução" é pequena demais para aparecer nos dados: o código em disputa tem 5 funções e o Mutante só troca um trecho de uma linha. A proposta é transformar o projeto num **experimento com resultado mensurável**:

> **Pergunta de pesquisa:** qual estratégia de teste gerada por IA encontra mais bugs, de que dificuldade, com quantas alucinações e a que custo?

O resultado vira a principal evidência do relatório: **"medimos que", não "achamos que"**.

## Visão geral

```
 1. CAMPO MAIOR           campos/pedidos/pedidos.py  (~15 funções, com funções compostas)
 2. BANCO DE MUTANTES     4 níveis de dificuldade, gerado UMA vez e reutilizado por todas as estratégias
 3. ESTRATÉGIAS           5 formas de o Caçador escrever testes, a partir da especificação, SEM ver o bug
 4. AVALIAÇÃO             cada suíte roda contra TODOS os mutantes → matriz estratégia × nível
 5. VISUALIZAÇÃO          página /laboratorio no painel: mapa de calor, gráficos, galeria de mutantes
```

A Arena atual (`arena.py`, `painel.py`) **continua intacta** como demo ao vivo. O Laboratório é um modo novo.

## 1. Campo maior: `campos/pedidos/pedidos.py`

Funções puras (sem estado global), com **docstrings precisas** (são a especificação):

| # | Função | Regra (resumo) |
|---|---|---|
| 1 | `subtotal(itens)` | soma `preco * quantidade`, `round(2)`; lista vazia → 0.0 |
| 2 | `desconto_volume(qtd)` | ≥100 → 10%; ≥50 → 5%; senão 0 |
| 3 | `desconto_categoria(categoria)` | bebidas 3%, limpeza 5%, mercearia 2%, outras 0 |
| 4 | `aplicar_cupom(valor, cupom)` | `PRIMEIRA10` −10%; `MENOS20` −R$ 20 se valor ≥ 100; nunca negativo |
| 5 | `aliquota_icms(uf)` | GO 17%, DF 18%, SP 18%, outras 12% |
| 6 | `imposto(valor, uf)` | `round(valor * aliquota_icms(uf), 2)` |
| 7 | `peso_total(itens)` | soma `peso_kg * quantidade`, `round(3)` |
| 8 | `frete(subtotal, uf, peso_kg)` | GO com subtotal ≥ 300 → 0; base GO 15 / DF 25 / outras 40; + R$ 2 por kg acima de 10 kg (arredonda o excedente para cima) |
| 9 | `prazo_entrega(uf, peso_kg)` | GO 1 dia, DF 2, outras 5; +2 dias se peso > 50 kg |
| 10 | `validar_item(item)` | True se `preco > 0` e `quantidade` inteiro > 0 |
| 11 | `reservar_estoque(estoque, itens)` | devolve **novo** dict com as quantidades baixadas; se faltar qualquer item, devolve `None` e não altera nada (tudo ou nada) |
| 12 | `parcelas(total, n)` | n de 1 a 12; até 3x sem juros; acima disso juros compostos de 1,99% a.m.: `total * 1.0199**n / n`; fora da faixa → `ValueError` |
| 13 | `pontos_fidelidade(total)` | 1 ponto a cada R$ 10 inteiros; pedidos ≥ 500 ganham pontos em dobro |
| 14 | `total_pedido(itens, uf, cupom=None)` | por item aplica desconto de categoria → desconto de volume → cupom → soma imposto → soma frete (calculado sobre o subtotal **sem** descontos e o peso total) |
| 15 | `resumo_pedido(itens, uf, cupom=None)` | dict com `total`, `frete`, `prazo`, `pontos` |

Cada item: `{"sku", "preco", "quantidade", "categoria", "peso_kg"}`.

Também criar:
- `campos/pedidos/test_base.py`: suíte inicial **fraca** (2 ou 3 testes);
- `campos/pedidos/oraculo.py`: gerador de entradas (valores-limite + aleatórios) para **cada** função, usado pelo oráculo diferencial.

## 2. Banco de mutantes em 4 níveis

Gerado uma vez e salvo em `laboratorio/mutantes/N<nivel>_<id>.json` (código mutado, diff, função afetada, prova do oráculo). **Todas as estratégias enfrentam os mesmos mutantes**, para a comparação ser justa.

| Nível | O que muda | Como gerar |
|---|---|---|
| **N1** | um operador ou constante (`>=` → `>`, `0.10` → `0.01`) | **operadores clássicos de mutation testing via AST** (determinístico, rápido, gera dezenas) |
| **N2** | uma condição ou expressão inteira (negar condição, trocar `and`/`or`, remover uma cláusula) | operadores AST |
| **N3** | **uma função inteira reescrita** com um bug semântico sutil | **LLM (Mutante)** via MCP: ferramenta `reescrever_funcao(nome, codigo_novo, justificativa)` |
| **N4** | **bug de interação**: reescrita de uma função composta (`total_pedido`, `resumo_pedido`, `frete`, `reservar_estoque`), errando a ordem ou a base de cálculo | LLM, mesma ferramenta, restrita às funções compostas |

Regras do árbitro para aceitar um mutante (as mesmas da Arena):
1. o código compila; nenhum import ou nome proibido; sem comentários ou strings longas (anti-injeção);
2. na reescrita de função: **mesmo nome e mesma assinatura**; a docstring original é reinserida automaticamente (a especificação não pode mudar);
3. o **oráculo diferencial** prova que o comportamento mudou (senão é equivalente e é descartado);
4. o mutante **sobrevive à suíte base** (senão é trivial).

Meta: ~20 mutantes em N1 e N2, ~12 em N3 e N4.

**Comparação bônus:** mutantes "clássicos" (N1, N2) contra mutantes "inteligentes" do LLM (N3, N4). Qual tipo é mais difícil de detectar?

## 3. As 5 estratégias do Caçador

Cada estratégia é um **prompt diferente**. O Caçador recebe a especificação e o código **correto** de uma função por vez (ferramenta MCP `ler_funcao`) e envia testes (`enviar_testes(funcao, codigo)`). Ele **nunca vê os mutantes**: é como um QA escrevendo testes antes do bug existir.

| # | Estratégia | O que o prompt pede |
|---|---|---|
| E1 | **Exemplos da docstring** | um teste por regra, com valores "típicos" |
| E2 | **Análise de valor-limite** | testar exatamente nos limites (49/50/99/100; 299.99/300; 10 kg; 3x/4x...) |
| E3 | **Partição de equivalência e tabela de decisão** | uma classe de entrada por partição; combinações de condições (UF × subtotal × peso) |
| E4 | **Testes baseados em propriedades** (Hypothesis) | invariantes: "total nunca negativo", "desconto nunca maior que o valor", "reservar_estoque não altera a entrada" |
| E5 | **Testes metamórficos e diferenciais** | relações entre execuções: "aumentar a quantidade nunca diminui o subtotal", "aplicar cupom duas vezes ≠ uma vez", "trocar a ordem dos itens não muda o total" |

Detalhes:
- **Filtro de alucinação**: testes que falham no código **correto** são descartados. O Caçador recebe o aviso "expectativa errada" (sem o valor certo) e pode corrigir **uma vez**. Registrar a taxa de alucinação da **primeira** tentativa e a final.
- Gerar **função por função** (15 chamadas curtas), e não a suíte inteira de uma vez: o modelo de 7B se perde com respostas longas.
- Rodar **2 ou 3 amostras** por estratégia, para medir a variância.
- E4 e E5 precisam de `hypothesis` (adicionar ao `requirements.txt` e à lista de imports permitidos do árbitro; usar um `conftest.py` na sandbox com `max_examples=60, deadline=None`).

## 4. Avaliação

Para cada suíte (estratégia × amostra), rodar contra **todos** os mutantes e medir:

| Métrica | Como |
|---|---|
| **Mutation score por nível** | mutantes mortos ÷ mutantes do nível |
| Taxa de alucinação | testes descartados ÷ testes gerados (1ª tentativa e final) |
| Custo | tokens gerados e tempo de GPU |
| Detecção por função | quais funções cada estratégia protege melhor |
| Mutantes imortais | os que nenhuma estratégia detectou (galeria) |

Desempenho: são ~60 mutantes × 5 estratégias × 2 ou 3 amostras, ou seja, centenas de execuções de pytest. Paralelizar com `concurrent.futures.ThreadPoolExecutor` (a máquina tem 12 núcleos): cada execução é um subprocesso isolado, como já faz `arbitro.rodar_pytest`.

Resultado esperado (ilustrativo):

```
                    N1     N2     N3     N4    alucinação   tokens
E1 exemplos        60%    40%    20%    10%       35%        8k
E2 valor-limite    85%    55%    30%    15%       40%        9k
E3 partição        ...
E4 propriedades    90%    80%    70%    55%       15%       11k
E5 metamórficos    ...
```

## 5. Visualização: página `/laboratorio` no painel

- **Mapa de calor** estratégia × nível (a matriz acima);
- barras de **alucinação** e de **custo** por estratégia;
- detecção **por função** (quais funções ficaram desprotegidas);
- **galeria de mutantes**: diff de cada função reescrita pelo LLM, qual estratégia a pegou e a prova do oráculo;
- progresso ao vivo enquanto o experimento roda (o painel já tem a infraestrutura de eventos e SSE);
- botão para rodar cada fase pelo navegador.

## Plano de implementação (ordem sugerida)

| Etapa | Arquivos | Estimativa |
|---|---|---|
| 1. Campo maior + suíte base + gerador do oráculo | `campos/pedidos/*` | 45 min |
| 2. Generalizar o árbitro: nome do módulo como parâmetro, oráculo por campo, reescrita de função via AST, Hypothesis permitido | `arbitro.py` | 45 min |
| 3. Mutantes N1/N2 por operadores AST | `laboratorio/operadores.py` | 30 min |
| 4. Servidor MCP do laboratório (`listar_funcoes`, `ler_funcao`, `reescrever_funcao`, `enviar_testes`) + mutantes N3/N4 pelo LLM | `servidor_laboratorio.py`, `laboratorio.py` | 1 h (+ ~40 min de GPU) |
| 5. As 5 estratégias do Caçador + geração das suítes | `laboratorio.py` | 1 h (+ ~1 h de GPU) |
| 6. Avaliação em paralelo e `laboratorio/resultados/*.json` | `laboratorio.py` | 30 min |
| 7. Página `/laboratorio` com os gráficos | `painel/laboratorio.html`, `painel.py` | 1 h |
| 8. Documentação e commits | `README.md`, `docs/` | contínuo |

CLI sugerida:
```bash
python laboratorio.py mutantes      # gera o banco de mutantes (N1..N4)
python laboratorio.py estrategias   # gera as suítes das 5 estratégias
python laboratorio.py avaliar       # roda a matriz e grava os resultados
python laboratorio.py tudo          # as três fases em sequência
```

## Reaproveitar do código atual

| Já existe | Onde | Uso no laboratório |
|---|---|---|
| Sandbox pytest isolada | `arbitro.rodar_pytest` | avaliar cada suíte × mutante |
| Validação AST e anti-injeção | `arbitro.validar_mutacao`, `_checar_nomes` | validar os mutantes |
| Oráculo diferencial | `arbitro.oraculo_diferencial` | generalizar para o gerador do novo campo |
| Filtro de alucinação por função | `arbitro.testes_que_falham`, `remover_funcoes` | filtrar os testes das estratégias |
| Streaming do Ollama e parser de tool calls | `arena.chat_em_stream`, `arena.extrair_chamadas` | laço dos agentes do laboratório |
| Painel com SSE e tema visual | `painel.py`, `painel/` | página `/laboratorio` |

## Preparar o outro computador

```bash
git clone https://github.com/Davi-MTS/arena-mutantes.git
cd arena-mutantes
pip install -r requirements.txt
pip install hypothesis              # necessário para as estratégias E4/E5
# instalar o Ollama (https://ollama.com) e baixar o modelo:
ollama pull qwen2.5-coder:7b
python painel.py                    # conferir se a Arena funciona antes de começar
```

Observações do ambiente original (GTX 1660 Super, 6 GB):
- Qwen2.5-Coder 7B em Q4 roda a ~22–25 tokens/s com `num_ctx=6144`. Numa GPU com mais VRAM, dá para aumentar o contexto e usar modelos maiores (ex.: 14B), o que tende a reduzir as alucinações e é mais uma variável interessante para o experimento.
- O SDK do MCP está fixado em `<2` (a versão 2 renomeou APIs).
- Em pastas com caminho muito longo no Windows, habilite `git config core.longpaths true`.

## Para uma sessão do Claude Code continuar

> "Leia `docs/proximo-passo-laboratorio.md` e implemente o Laboratório seguindo o plano de implementação, etapa por etapa. Mantenha a Arena atual funcionando. Faça commit e push no GitHub a cada etapa concluída, com mensagens em português."
