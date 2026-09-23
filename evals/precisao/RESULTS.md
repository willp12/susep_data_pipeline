# Resultado — rodada de 22/09/2026

45 runs (5 perguntas × 3 braços × 3 repetições) com `claude-opus-4-7`, o modelo
que o alias `opus` resolve no CLI 2.1.142 que vem com o SDK 0.2.82. É o mesmo da
produção. Snapshot da bronze de 21/09/2026, com 13 cargas acumuladas. Custo total
de US$ 3,07 a preço de lista da API. Desenho e método: [README.md](README.md).

## Leitura

- **O mart acerta tudo e é o mais barato por resposta certa.** C: 15 de 15,
  US$ 0,04 por resposta certa, 3,5 turnos e 12,5 MiB lidos no BigQuery por run.
  A: US$ 0,14 por resposta certa, 3,7 vezes mais.
- **A skill empata no acerto, mas não no custo.** B: 15 de 15, com a skill aberta
  nos 15 runs, sempre no 2º turno. Cada resposta certa custa 1,6 vez a do C, e
  cada run lê 48 vezes mais dados, porque toda query refaz na bronze o que o
  dbt fez uma vez.
- **O "13 de 15" do A esconde o risco.** Os 15 runs do A tiveram ao menos uma
  query que somou todas as 13 cargas. 7 perceberam e refizeram a conta. 6
  acertaram sem nunca filtrar a carga: 3 na variação, porque a razão entre os
  anos cancela a inflação, e 3 no último mês, porque julho de 2026 só existe na
  carga de 21/09. Junho aparece em 3 cargas e maio em 5: a mesma query, feita
  para junho, daria 3 vezes o valor. 2 entregaram o valor 13,000 vezes maior. Só
  7 dos 15 runs do A acertaram pelo motivo certo.
- **Certo pelo motivo errado, em texto.** O A-q5-r1 acertou a variação (9,38%)
  e escreveu na própria resposta que o prêmio direto de 2024 foi R$ 2,48 tri. O
  certo é R$ 191,0 bi.
- **O bug do `1451be3` voltou sozinho.** O A-q3-r2 filtrou o grupo de ramos
  Automóvel por `cogrupo = '05'` antes de trocar para o prefixo do ramo.
- **Os atalhos ingênuos, na pergunta 1.** Somar todas as cargas dá 13,00 vezes o
  valor certo. Converter o texto sem trocar a vírgula devolve 0,95% dele, porque
  quase todo o dinheiro está nas linhas com centavos.

## Números

| Braço | Acerto | Custo médio por run | Custo por resposta certa | Tokens de entrada | Tokens de saída | Turnos | Queries | MiB lidos no BigQuery | Tempo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A, bronze cru | 13/15 | US$ 0,12 | US$ 0,14 | 44.452 | 2.167 | 8,2 | 3,9 | 1.239,7 | 43 s |
| B, bronze + skill | 15/15 | US$ 0,06 | US$ 0,06 | 21.512 | 1.037 | 5,4 | 1,4 | 595,2 | 21 s |
| C, mart dbt | 15/15 | US$ 0,04 | US$ 0,04 | 17.817 | 815 | 3,5 | 1,5 | 12,5 | 17 s |

Acertos por pergunta (de 3):

| Braço | q1 total 2024 | q2 último mês | q3 Automóvel | q4 top 5 | q5 variação |
| --- | --- | --- | --- | --- | --- |
| A | 2 | 3 | 2 | 3 | 3 |
| B | 3 | 3 | 3 | 3 | 3 |
| C | 3 | 3 | 3 | 3 | 3 |

Como cada run chegou à resposta:

| Braço | Certo limpo | Certo corrigindo | Certo sem filtrar | Errado |
| --- | --- | --- | --- | --- |
| A | 0 | 7 | 6 | 2 |
| B | 15 | 0 | 0 | 0 |
| C | 15 | 0 | 0 | 0 |

## Auditoria da rodada

- 45 de 45 runs terminaram com `success`, todos com resposta pela saída
  estruturada e nenhum problema de isolamento na mensagem de init.
- Tools vistas pelo modelo: as três do `bq` e a `StructuredOutput`, mais a
  `Skill` no B. Nenhuma negação de permissão.
- O runner removeu 34 variáveis herdadas da sessão do Claude Code que o
  disparou (lista em `results/full/meta.json`).

## Limites

- 45 runs, um modelo, um snapshot e cinco perguntas: mostra direção, não é prova
  estatística.
- A skill foi escrita a partir do próprio dbt, então o B está no melhor cenário.
- A classificação "certo sem filtrar" e "certo corrigindo" é uma heurística sobre
  o SQL executado; os casos acima foram conferidos à mão nos transcripts.
