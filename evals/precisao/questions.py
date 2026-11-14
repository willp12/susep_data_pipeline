"""As perguntas do experimento, o formato de resposta e o SQL de referência.

Todas giram em torno do prêmio direto, e cada uma cai numa armadilha que já
quebrou o projeto de verdade. O texto enviado ao agente é o mesmo nos três
braços.

Cada pergunta tem três SQLs de referência, caminhos independentes para a mesma
resposta: um lê o mart, outro aplica as regras à mão sobre a bronze e o
terceiro, em DuckDB, faz o mesmo direto nos CSVs do zip da SUSEP. O gabarito
só vale se mart e bronze baterem (truth.py); os CSVs são conferidos contra ele
(csvdata.py). Os placeholders ``{bronze}`` e ``{marts}`` recebem os datasets do
config, e ``{dir}`` a pasta dos CSVs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

AnswerKind = Literal["valor", "mes_valor", "ranking", "percentual"]


@dataclass(frozen=True)
class Question:
    qid: str
    kind: AnswerKind
    text: str
    trap: str
    mart_sql: str
    bronze_sql: str
    csv_sql: str


QUESTIONS: tuple[Question, ...] = (
    Question(
        qid="q1",
        kind="valor",
        text=(
            "Qual foi o prêmio direto total do mercado segurador brasileiro em 2024, "
            "somando de janeiro a dezembro?"
        ),
        trap="a bronze acumula um snapshot por carga e guarda valores em texto com vírgula",
        mart_sql="""
SELECT SUM(premio_direto) AS valor
FROM `{marts}.fct_seguros`
WHERE periodo_ref BETWEEN DATE '2024-01-01' AND DATE '2024-12-01'
""",
        bronze_sql="""
WITH snap AS (
  SELECT damesano, premio_direto
  FROM `{bronze}.ses_seguros`
  WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `{bronze}.ses_seguros`)
)
SELECT SUM(SAFE_CAST(REPLACE(premio_direto, ',', '.') AS NUMERIC)) AS valor
FROM snap
WHERE damesano BETWEEN '202401' AND '202412'
""",
        csv_sql="""
SELECT SUM(TRY_CAST(REPLACE(premio_direto, ',', '.') AS DECIMAL(38, 9))) AS valor
FROM read_csv('{dir}/Ses_seguros.csv', delim=';', header=true,
              all_varchar=true)
WHERE damesano BETWEEN '202401' AND '202412'
""",
    ),
    Question(
        qid="q2",
        kind="mes_valor",
        text=(
            "Qual é o mês mais recente com dados disponíveis, e qual foi o prêmio direto "
            "total do mercado nesse mês?"
        ),
        trap="achar o snapshot mais recente e, nele, o mês mais recente",
        mart_sql="""
SELECT FORMAT_DATE('%Y-%m', periodo_ref) AS mes, SUM(premio_direto) AS valor
FROM `{marts}.fct_seguros`
WHERE periodo_ref = (SELECT MAX(periodo_ref) FROM `{marts}.fct_seguros`)
GROUP BY mes
""",
        bronze_sql="""
WITH snap AS (
  SELECT damesano, premio_direto
  FROM `{bronze}.ses_seguros`
  WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `{bronze}.ses_seguros`)
)
SELECT
  CONCAT(SUBSTR(damesano, 1, 4), '-', SUBSTR(damesano, 5, 2)) AS mes,
  SUM(SAFE_CAST(REPLACE(premio_direto, ',', '.') AS NUMERIC)) AS valor
FROM snap
WHERE damesano = (SELECT MAX(damesano) FROM snap)
GROUP BY mes
""",
        csv_sql="""
WITH fato AS (
  SELECT damesano, premio_direto
  FROM read_csv('{dir}/Ses_seguros.csv', delim=';', header=true,
                all_varchar=true)
)
SELECT
  SUBSTR(damesano, 1, 4) || '-' || SUBSTR(damesano, 5, 2) AS mes,
  SUM(TRY_CAST(REPLACE(premio_direto, ',', '.') AS DECIMAL(38, 9))) AS valor
FROM fato
WHERE damesano = (SELECT MAX(damesano) FROM fato)
GROUP BY mes
""",
    ),
    Question(
        qid="q3",
        kind="valor",
        text=(
            "Qual foi o prêmio direto do grupo de ramos Automóvel em 2024, "
            "somando de janeiro a dezembro?"
        ),
        trap="grupo de ramos são os 2 primeiros dígitos do ramo, não o cogrupo (commit 1451be3)",
        mart_sql="""
SELECT SUM(premio_direto) AS valor
FROM `{marts}.fct_seguros`
WHERE ramo_group_code = '05'
  AND periodo_ref BETWEEN DATE '2024-01-01' AND DATE '2024-12-01'
""",
        bronze_sql="""
WITH snap AS (
  SELECT damesano, coramo, premio_direto
  FROM `{bronze}.ses_seguros`
  WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `{bronze}.ses_seguros`)
),
grupo AS (
  SELECT TRIM(GRACODIGO) AS codigo
  FROM `{bronze}.ses_gruposramos`
  WHERE GRANOME LIKE '%Automóvel%'
)
SELECT SUM(SAFE_CAST(REPLACE(premio_direto, ',', '.') AS NUMERIC)) AS valor
FROM snap
WHERE SUBSTR(coramo, 1, 2) = (SELECT codigo FROM grupo)
  AND damesano BETWEEN '202401' AND '202412'
""",
        csv_sql="""
WITH fato AS (
  SELECT damesano, coramo, premio_direto
  FROM read_csv('{dir}/Ses_seguros.csv', delim=';', header=true,
                all_varchar=true)
),
grupo AS (
  SELECT TRIM(GRACODIGO) AS codigo
  FROM read_csv('{dir}/ses_gruposramos.csv', delim=';', header=true,
                all_varchar=true, quote='')
  WHERE GRANOME LIKE '%Automóvel%'
)
SELECT SUM(TRY_CAST(REPLACE(premio_direto, ',', '.') AS DECIMAL(38, 9))) AS valor
FROM fato
WHERE SUBSTR(coramo, 1, 2) = (SELECT codigo FROM grupo)
  AND damesano BETWEEN '202401' AND '202412'
""",
    ),
    Question(
        qid="q4",
        kind="ranking",
        text=(
            "Quais foram as 5 seguradoras com maior prêmio direto em 2024, somando de "
            "janeiro a dezembro? Para cada uma, informe o código SUSEP, o nome oficial "
            "e o valor."
        ),
        trap="o nome vem de uma tabela de cadastro; deduzir pelo código é o bug do c5329c7",
        mart_sql="""
SELECT entity_code AS codigo, ANY_VALUE(entity_name) AS nome, SUM(premio_direto) AS valor
FROM `{marts}.fct_seguros`
WHERE periodo_ref BETWEEN DATE '2024-01-01' AND DATE '2024-12-01'
GROUP BY entity_code
ORDER BY valor DESC
LIMIT 5
""",
        bronze_sql="""
WITH snap AS (
  SELECT damesano, coenti, premio_direto
  FROM `{bronze}.ses_seguros`
  WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `{bronze}.ses_seguros`)
),
agg AS (
  SELECT coenti, SUM(SAFE_CAST(REPLACE(premio_direto, ',', '.') AS NUMERIC)) AS valor
  FROM snap
  WHERE damesano BETWEEN '202401' AND '202412'
  GROUP BY coenti
),
cias AS (
  SELECT TRIM(Coenti) AS codigo, ANY_VALUE(TRIM(Noenti)) AS nome
  FROM `{bronze}.ses_cias`
  GROUP BY codigo
)
SELECT agg.coenti AS codigo, cias.nome, agg.valor
FROM agg
LEFT JOIN cias ON cias.codigo = TRIM(agg.coenti)
ORDER BY agg.valor DESC
LIMIT 5
""",
        csv_sql="""
WITH fato AS (
  SELECT damesano, coenti, premio_direto
  FROM read_csv('{dir}/Ses_seguros.csv', delim=';', header=true,
                all_varchar=true)
),
agg AS (
  SELECT coenti, SUM(TRY_CAST(REPLACE(premio_direto, ',', '.') AS DECIMAL(38, 9))) AS valor
  FROM fato
  WHERE damesano BETWEEN '202401' AND '202412'
  GROUP BY coenti
),
cias AS (
  SELECT TRIM(Coenti) AS codigo, ANY_VALUE(TRIM(Noenti)) AS nome
  FROM read_csv('{dir}/Ses_cias.csv', delim=';', header=true,
                all_varchar=true, quote='', strict_mode=false, null_padding=true)
  GROUP BY codigo
)
SELECT agg.coenti AS codigo, cias.nome, agg.valor
FROM agg
LEFT JOIN cias ON cias.codigo = TRIM(agg.coenti)
ORDER BY agg.valor DESC
LIMIT 5
""",
    ),
    Question(
        qid="q5",
        kind="percentual",
        text=(
            "Qual foi a variação percentual do prêmio direto total do mercado de 2023 "
            "para 2024, comparando os anos completos?"
        ),
        trap="controle: somar todos os snapshots infla os dois anos e a razão quase não muda",
        mart_sql="""
SELECT
  SUM(IF(EXTRACT(YEAR FROM periodo_ref) = 2023, premio_direto, 0)) AS v2023,
  SUM(IF(EXTRACT(YEAR FROM periodo_ref) = 2024, premio_direto, 0)) AS v2024
FROM `{marts}.fct_seguros`
WHERE periodo_ref BETWEEN DATE '2023-01-01' AND DATE '2024-12-01'
""",
        bronze_sql="""
WITH snap AS (
  SELECT damesano, SAFE_CAST(REPLACE(premio_direto, ',', '.') AS NUMERIC) AS premio
  FROM `{bronze}.ses_seguros`
  WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `{bronze}.ses_seguros`)
)
SELECT
  SUM(IF(STARTS_WITH(damesano, '2023'), premio, 0)) AS v2023,
  SUM(IF(STARTS_WITH(damesano, '2024'), premio, 0)) AS v2024
FROM snap
WHERE damesano BETWEEN '202301' AND '202412'
""",
        csv_sql="""
WITH fato AS (
  SELECT damesano, TRY_CAST(REPLACE(premio_direto, ',', '.') AS DECIMAL(38, 9)) AS premio
  FROM read_csv('{dir}/Ses_seguros.csv', delim=';', header=true,
                all_varchar=true)
)
SELECT
  SUM(CASE WHEN starts_with(damesano, '2023') THEN premio ELSE 0 END) AS v2023,
  SUM(CASE WHEN starts_with(damesano, '2024') THEN premio ELSE 0 END) AS v2024
FROM fato
WHERE damesano BETWEEN '202301' AND '202412'
""",
    ),
)

QUESTIONS_BY_ID: dict[str, Question] = {q.qid: q for q in QUESTIONS}


def render_sql(template: str, *, bronze: str, marts: str) -> str:
    """Fill the dataset placeholders. Datasets come from settings, never from input."""
    return template.format(bronze=bronze, marts=marts)


def render_csv_sql(template: str, files: Path) -> str:
    """Fill the CSV folder placeholder with an absolute, forward-slash path."""
    return template.format(dir=files.resolve().as_posix())


# Formato da resposta, pedido ao agente via output_format (JSON schema). Um
# formato só para as cinco perguntas: cada uma preenche o campo que lhe cabe.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "valor_reais": {
            "type": ["number", "null"],
            "description": (
                "O valor pedido, em reais (R$), como número e sem escala: nada de "
                "milhões ou bilhões. null se a pergunta não pede um valor único."
            ),
        },
        "mes_referencia": {
            "type": ["string", "null"],
            "description": "Mês no formato YYYY-MM, quando a pergunta pede um mês.",
        },
        "variacao_percentual": {
            "type": ["number", "null"],
            "description": "Variação em pontos percentuais: 12.34 para uma alta de 12,34%.",
        },
        "ranking": {
            "type": ["array", "null"],
            "description": "Quando a pergunta pede um ranking, do maior para o menor.",
            "items": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string"},
                    "nome": {"type": "string"},
                    "valor_reais": {"type": "number"},
                },
                "required": ["codigo", "nome", "valor_reais"],
            },
        },
        "queries_usadas": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "O query_no de cada query que sustenta a resposta.",
        },
        "observacoes": {
            "type": "string",
            "description": "Premissas e ressalvas, em uma ou duas frases.",
        },
    },
    "required": [
        "valor_reais",
        "mes_referencia",
        "variacao_percentual",
        "ranking",
        "queries_usadas",
        "observacoes",
    ],
}
