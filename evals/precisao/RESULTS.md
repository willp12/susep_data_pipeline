# Resultado — rodadas de 22 e 23/09/2026

60 runs: 5 perguntas × 4 braços × 3 repetições. A, B e C rodaram em 22/09; D, em
23/09. Snapshot da bronze de 21/09/2026, com 13 cargas acumuladas; o D leu os CSVs
do mesmo zip, conferido pelo SHA-256 registrado na `ingestion_log`. Desenho e
método: [README.md](README.md).

## Modelo e custo total

- **Agente: `claude-opus-4-7`** nos 60 runs. É para onde o alias `opus` aponta no
  Claude Code 2.1.142, o que vem com o SDK 0.2.82, o mesmo da produção.
- O Claude Code também faz, sozinho, uma chamada pequena ao
  `claude-haiku-4-5-20251001` em cada run: cerca de 500 tokens e 1% do custo.
- **1.900.671 tokens e US$ 4,45 no total**, a preço de lista da API (US$ 4,41 do
  Opus e US$ 0,03 do Haiku). A conta é por assinatura, então o gasto real foi zero;
  o número serve para comparar os braços.

O custo que o SDK registra é exatamente tokens × preço de tabela, conferido run a
run. No Opus 4.7, por milhão de tokens: entrada US$ 5, escrita de cache US$ 6,25,
leitura de cache US$ 0,50 e saída US$ 25. Por isso o volume de tokens e o custo
contam histórias diferentes:

| Tipo de token | Volume | Custo |
| --- | --- | --- |
| Leitura de cache | 81,9% | 17,5% |
| Escrita de cache | 11,8% | 31,5% |
| Saída | 4,7% | 50,2% |
| Entrada nova | 1,6% | 0,8% |

Tokens por resposta certa são um bom indicador do custo de IA, porque não
dependem de preço nem do tipo de conta, e ordenam os braços como o dinheiro. Mas
quem paga a conta é a saída, que é onde o agente raciocina e escreve SQL.

## Leitura

- **O mart acerta tudo e é o mais barato.** C: 15 de 15, US$ 0,04 e 19 mil tokens
  por resposta certa, 3,5 turnos e 12,5 MiB lidos no BigQuery por run. A: US$ 0,14
  por resposta certa, 3,7 vezes mais.
- **A skill empata no acerto, não no custo.** B: 15 de 15, com a skill aberta nos
  15 runs, sempre no 2º turno. Cada resposta certa custa 1,6 vez a do C, e cada
  run lê 48 vezes mais dados, porque toda query refaz na bronze o que o dbt fez
  uma vez.
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
- **O bug do `1451be3` voltou sozinho.** Um run do A e um do D filtraram o grupo
  de ramos Automóvel por `cogrupo = '05'` antes de trocar para o prefixo do ramo.
- **O CSV cru também chega, mas mais caro e com sorte.** D: 15 de 15, US$ 0,09 e
  37 mil tokens por resposta certa, 2,5 vezes o mart, em 8,2 turnos por run. Não
  tem a armadilha das cargas, que é criada pelo próprio pipeline, mas tem as do
  arquivo cru: 14 dos 15 runs tentaram somar o valor ainda como texto, e 5
  esbarraram no encoding dos cadastros. Os cadastros são Windows-1252; sem a
  extensão `encodings` do DuckDB, o contorno do agente foi ler com
  `ignore_errors`, que descarta em silêncio 225 das 769 seguradoras. Os 3 runs da
  q4 acertaram porque os cinco maiores nomes de 2024 não têm acento.
- **Os atalhos ingênuos, na q1.** Somar todas as cargas dá 13,00 vezes o valor
  certo. Converter o texto sem trocar a vírgula devolve 0,95% dele, porque quase
  todo o dinheiro está nas linhas com centavos.

## Números

| Braço | Acerto | Custo por run | Custo por resposta certa | Tokens por resposta certa | Turnos | Queries | MiB lidos no BigQuery | Tempo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A, bronze cru | 13/15 | US$ 0,12 | US$ 0,14 | 54.356 | 8,2 | 3,9 | 1.239,7 | 43 s |
| B, bronze + skill | 15/15 | US$ 0,06 | US$ 0,06 | 23.038 | 5,4 | 1,4 | 595,2 | 21 s |
| C, mart dbt | 15/15 | US$ 0,04 | US$ 0,04 | 19.122 | 3,5 | 1,5 | 12,5 | 17 s |
| D, CSV cru | 15/15 | US$ 0,09 | US$ 0,09 | 37.443 | 8,2 | 3,9 | local | 33 s |

O BigQuery é 6% do custo no A e no B, 0,2% no C e zero no D, que roda local.

Tokens por braço, somando os dois modelos:

| Braço | Entrada | Escrita de cache | Leitura de cache | Saída | Total |
| --- | --- | --- | --- | --- | --- |
| A | 7.631 | 92.840 | 573.387 | 32.766 | 706.624 |
| B | 7.401 | 46.273 | 276.086 | 15.810 | 345.570 |
| C | 7.311 | 18.743 | 248.280 | 12.498 | 286.832 |
| D | 7.493 | 66.004 | 458.981 | 29.167 | 561.645 |

Acertos por pergunta (de 3):

| Braço | q1 total 2024 | q2 último mês | q3 Automóvel | q4 top 5 | q5 variação |
| --- | --- | --- | --- | --- | --- |
| A | 2 | 3 | 2 | 3 | 3 |
| B | 3 | 3 | 3 | 3 | 3 |
| C | 3 | 3 | 3 | 3 | 3 |
| D | 3 | 3 | 3 | 3 | 3 |

Como cada run chegou à resposta:

| Braço | Certo limpo | Certo corrigindo | Certo por sorte | Errado |
| --- | --- | --- | --- | --- |
| A | 0 | 7 | 6 | 2 |
| B | 15 | 0 | 0 | 0 |
| C | 15 | 0 | 0 | 0 |
| D | 0 | 12 | 3 | 0 |

## Auditoria

- 60 de 60 runs terminaram com `success`, todos com resposta pela saída
  estruturada e nenhum problema de isolamento na mensagem de init.
- Tools vistas pelo modelo: as três do braço e a `StructuredOutput`, mais a
  `Skill` no B. Nenhuma negação de permissão.
- O gabarito bate em três derivações independentes: mart, bronze e os CSVs.
- Os runs marcados como "por sorte" e os errados foram conferidos à mão nos
  transcripts. Um run do D que a primeira versão da heurística marcava como sorte
  (D-q3-r1) foi reclassificado: a lista de ramos lida com `ignore_errors` era só
  contexto, e o valor saiu de uma soma direta no fato.
- O runner removeu 34 variáveis herdadas da sessão do Claude Code que o disparou
  (lista nos `meta-*.json` de `results/full`).

## Limites

- Um modelo, um snapshot e cinco perguntas, com três repetições: mostra direção,
  não é prova estatística.
- A skill foi escrita a partir do próprio dbt, então o B está no melhor cenário.
- O D rodou um dia depois, e sem a extensão `encodings` do DuckDB.
- O glossário do C sai do `manifest.json`; um `dbt parse` novo pode mudar a ordem
  das seções, não o conteúdo.
- "Certo" quer dizer que bate com a verdade modelada no projeto, não com um
  número oficial publicado pela SUSEP.
