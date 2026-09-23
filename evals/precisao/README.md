# Precisão e custo por camada: bronze × bronze + skill × mart

O projeto defende que regra de negócio deve sair do prompt e virar SQL testado
no dbt. Este experimento mede isso. O mesmo agente responde às mesmas perguntas
sobre prêmio direto em três configurações, e comparamos quantas respostas saem
certas e quanto custa cada resposta certa.

| Braço | Lê | Conhecimento de domínio | Como chega ao agente |
| --- | --- | --- | --- |
| A | `susep_ses_bronze` | nenhum, só os nomes das tabelas | — |
| B | `susep_ses_bronze` | as regras que o dbt implementa, em prosa | Agent Skill `susep-bronze`, que o modelo decide abrir |
| C | `susep_ses_marts` | o glossário do dbt | system prompt, como na produção |

B e C carregam o mesmo conhecimento: o [SKILL.md](skill/susep-bronze/SKILL.md)
foi escrito a partir de `stg_ses_seguros.sql`, `fct_seguros.sql`, das dims e do
`_models.yml`. A diferença é onde a regra vive. No B, ela é prosa que o LLM
precisa lembrar e aplicar a cada query. No C, é SQL testado, aplicado uma vez no
`dbt build`. A e B recebem o mesmo system prompt; a única diferença entre eles é
a skill existir.

Fica igual nos três braços: modelo (`opus`, como o cron semanal), prompt-base,
as três tools com descrições neutras, teto de 1 GiB por query, 20 turnos e
US$ 1,25 por run (os valores da produção), perguntas e formato de resposta. A
ordem dos runs é embaralhada com semente fixa.

## As perguntas

Todas sobre prêmio direto. Cada uma cai numa armadilha que já quebrou o projeto.

| # | Pergunta | Armadilha |
| --- | --- | --- |
| q1 | Prêmio direto total do mercado em 2024 | a bronze guarda um snapshot por carga (hoje são 13) e os valores são texto com vírgula |
| q2 | Mês mais recente e o prêmio direto dele | achar o snapshot e o mês mais recentes |
| q3 | Prêmio direto do grupo de ramos Automóvel em 2024 | grupo de ramos são os 2 primeiros dígitos do ramo, não o `cogrupo` (commit `1451be3`) |
| q4 | As 5 maiores seguradoras em 2024, com código, nome e valor | o nome vem do cadastro; deduzir pelo código é o bug do `c5329c7` |
| q5 | Variação % de 2023 para 2024 | controle: somar todos os snapshots infla os dois anos e a razão quase não muda |

## O gabarito

[truth.py](truth.py) calcula cada resposta por dois caminhos independentes, SQL
no mart e SQL na bronze aplicando as regras à mão, e só grava se os dois baterem
no centavo. Grava também quanto dariam os dois atalhos ingênuos na q1. No
snapshot de 21/09/2026:

- somar todos os snapshots dá **13,00 vezes** o valor certo;
- converter sem trocar a vírgula recupera **0,95%** do valor certo, porque quase
  todo o dinheiro está nas linhas com centavos.

## Como se mede

**Acerto por run.** Valor a até 0,5% do gabarito (pega soma de snapshots, grupo
errado e decimal perdido; perdoa arredondamento). Mês exato. Ranking com os 5
códigos na ordem, valores a até 0,5% e nomes que batem com o cadastro oficial.
Percentual a até 0,1 p.p. Cada erro recebe um rótulo (`snapshot_duplicado`,
`subcontagem`, `nome_inventado`, `escala_errada`…) e os errados são revisados à
mão pelo transcript.

**Custo por run.** `total_cost_usd` do SDK (preço de lista da API, mesmo quando
a conta é por assinatura), tokens, turnos e tempo. BigQuery pela estimativa sem
cache do dry-run, a US$ 6,25/TiB.

**A métrica principal é o custo por resposta certa**: o custo total do braço
dividido pelos acertos.

**Como o run chegou lá.** Acertar o número não basta: na bronze, uma soma sem
filtro de carga pode bater com o gabarito por sorte (numa razão, a inflação se
cancela; um mês que só existe na última carga não duplica). O `score.py` olha as
queries que a resposta cita e classifica cada run como certo limpo, certo
corrigindo (caiu na armadilha, mas a resposta se apoia em queries que filtram a
carga), certo sem filtrar (acertou por sorte do dado) ou errado.

## Isolamento

A produção não serve de base direta para o experimento, porque vaza
conhecimento em vários pontos. O harness corrige todos sem mexer nela:

- a descrição do `run_sql` e a mensagem de erro do teto mandam filtrar pelo
  último `_ingestion_date`: aqui as descrições são neutras;
- `describe_table` devolve as descrições de coluna: aqui elas são removidas;
- o glossário da produção junta bronze, staging e marts: o C recebe só o mart;
- cada braço só consulta o seu dataset (allowlist em `run_sql`,
  `describe_table` e `sample_rows`);
- `setting_sources=None` carrega as configurações do disco no SDK 0.2.82: aqui
  A e C usam `[]`, e B carrega só a skill, num diretório temporário;
- as tools internas do Claude Code ficam desligadas, menos a `Skill` no B;
- o runner remove as variáveis que um Claude Code pai exporta (`CLAUDE_*`,
  `ANTHROPIC_*`, `USE_STAGING_OAUTH`…) e dá a cada run um `CLAUDE_CONFIG_DIR`
  vazio, como a home do runner do CI.

Cada run confere a mensagem de init do CLI (tools, servidores MCP, skills, cwd)
e grava o que estiver fora do esperado em `isolation_problems`.
[tests/evals/test_arms.py](../../tests/evals/test_arms.py) tem um teste de
vazamento: nenhuma regra pode aparecer no prompt, nas perguntas, nas descrições
das tools ou nas mensagens de erro que A e B recebem.

## Rodar

Precisa do `.env` com `GCP_PROJECT_ID` e uma credencial do agente
(`CLAUDE_CODE_OAUTH_TOKEN` ou `ANTHROPIC_API_KEY`), mais o
`gcloud auth application-default login`. O `.env` é a única fonte de
configuração: variáveis herdadas do shell com prefixo `CLAUDE` ou `ANTHROPIC`
são descartadas.

```bash
cd dbt && uv run dbt parse --profiles-dir . && cd ..            # glossário do C
uv run python -m evals.precisao.truth                           # gabarito
uv run python -m evals.precisao.run --dry-run                   # plano e prompts
uv run python -m evals.precisao.run --out evals/precisao/results/smoke --questions q1 --reps 1
uv run python -m evals.precisao.run --out evals/precisao/results/full --reps 3
uv run python -m evals.precisao.score evals/precisao/results/full
```

Os mesmos passos existem como alvos do Makefile (`eval-truth`, `eval-dry`,
`eval-smoke`, `eval`, `eval-score`).

O `run` retoma de onde parou: runs terminados são pulados e os que caíram por
infraestrutura rodam de novo. `--max-total-usd` (padrão 40) para de lançar runs
ao passar do teto. Os resultados ficam em `results/`, fora do git; o resumo final
vai para [RESULTS.md](RESULTS.md).

No Windows sem `make`, rode os comandos acima direto. Se o `run` for disparado de
dentro de uma sessão do Claude Code, não há nada a fazer: ele descarta as
variáveis dessa sessão sozinho e registra os nomes em `meta.json`.

## Limites

- 45 runs, um modelo, um snapshot e cinco perguntas: o resultado mostra direção,
  não é prova estatística.
- A skill foi escrita por quem escreveu o mart, então o B está no melhor cenário.
- "Certo" quer dizer que bate com a verdade modelada no projeto, não com um
  número oficial publicado pela SUSEP.
