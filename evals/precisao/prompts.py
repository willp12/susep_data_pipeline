"""Prompts do experimento: um prompt-base neutro e o que muda por braço.

A e B recebem exatamente o mesmo system prompt; a única diferença entre eles é
a skill existir. C recebe as tabelas do mart e o glossário do dbt filtrado para
o mart, como na produção, só que sem as outras camadas.

Nada aqui pode ensinar regra de domínio: o teste de vazamento em
tests/evals/test_arms.py confere isso.
"""

from __future__ import annotations

from collections.abc import Sequence

BASE_PROMPT = """\
Você é analista de dados do mercado de seguros brasileiro. Responda à pergunta do
usuário consultando o BigQuery com as tools `bq` (describe_table, sample_rows e
run_sql).

- Toda cifra e todo nome da resposta precisam sair de uma query executada nesta
  sessão. Não use conhecimento prévio sobre o mercado e não estime valores.
- Use só as tabelas listadas em "Dados disponíveis".
- Valores monetários vão em reais (R$), como número, sem converter para milhões
  ou bilhões.
- Ao terminar, entregue a resposta no formato estruturado pedido e liste em
  `queries_usadas` o `query_no` das queries que a sustentam.
"""


def system_prompt(dataset: str, tables: Sequence[str], glossary: str | None = None) -> str:
    """The arm's system prompt: base + the tables it may read (+ the glossary for C)."""
    listing = "\n".join(f"- `{dataset}.{table}`" for table in tables)
    prompt = (
        f"{BASE_PROMPT}\n## Dados disponíveis\n\n"
        f"Dataset `{dataset}` no projeto padrão do BigQuery:\n\n{listing}\n"
    )
    if glossary:
        prompt += f"\n## Glossário (dbt docs)\n\n{glossary}\n"
    return prompt


# Braço D: o mesmo prompt-base, trocando tabelas por arquivos. Nada sobre
# encoding, separador ou tipos: descobrir isso é o que o braço mede.
CSV_BASE_PROMPT = """\
Você é analista de dados do mercado de seguros brasileiro. Responda à pergunta do
usuário consultando os arquivos CSV de uma pasta com as tools `csv` (list_files,
head_file e run_sql, que roda SQL no DuckDB).

- Toda cifra e todo nome da resposta precisam sair de uma query executada nesta
  sessão. Não use conhecimento prévio sobre o mercado e não estime valores.
- Use só os arquivos listados em "Dados disponíveis".
- Valores monetários vão em reais (R$), como número, sem converter para milhões
  ou bilhões.
- Ao terminar, entregue a resposta no formato estruturado pedido e liste em
  `queries_usadas` o `query_no` das queries que a sustentam.
"""


def csv_system_prompt(files: Sequence[str]) -> str:
    """Arm D's system prompt: the CSV files from the SUSEP zip, by name."""
    listing = "\n".join(f"- `{name}`" for name in files)
    return (
        f"{CSV_BASE_PROMPT}\n## Dados disponíveis\n\n"
        f"Arquivos da base SES, extraídos do zip que a SUSEP publica:\n\n{listing}\n"
    )
