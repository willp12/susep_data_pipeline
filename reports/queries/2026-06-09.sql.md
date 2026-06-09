# Apêndice de queries — 2026-06-09

Queries executadas pelo agente na geração de `2026-06-09.md`, na ordem em que rodaram. Os insights citam estas queries por número.

## Query 1

_1 linha(s), 13.6 MiB processados_

```sql
SELECT MAX(periodo_ref) AS max_periodo, MIN(periodo_ref) AS min_periodo, COUNT(DISTINCT periodo_ref) AS n_periodos FROM `susep_ses_marts.fct_seguros`
```

## Query 2

_20 linha(s), 17.6 MiB processados_

```sql
-- Q2: Overview ramo groups - total premio and loss ratio in last 3 years
SELECT
  ramo_group_code,
  ramo_group_name,
  SUM(premio_direto) AS premio_direto_total,
  SUM(premio_ganho) AS premio_ganho_total,
  SUM(sinistro_ocorrido) AS sinistro_ocorrido_total,
  SAFE_DIVIDE(SUM(sinistro_ocorrido), SUM(premio_ganho)) AS loss_ratio_global,
  SUM(desp_com) AS desp_com_total
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE_SUB(DATE '2026-02-01', INTERVAL 3 YEAR)
GROUP BY 1, 2
ORDER BY premio_direto_total DESC
```

## Query 3

_20 linha(s), 18.0 MiB processados_

```sql
-- Q3: Capitalização - market size and top players
SELECT
  entity_name,
  economic_group_name,
  SUM(premio_emitido_cap) AS premio_cap_total,
  SUM(sinistros_ocorridos_cap) AS sinistros_cap_total,
  SUM(recuperacao_sinistros_ocorridos_cap) AS recuperacao_cap_total,
  SAFE_DIVIDE(SUM(sinistros_ocorridos_cap), SUM(premio_emitido_cap)) AS loss_ratio_cap
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE_SUB(DATE '2026-02-01', INTERVAL 3 YEAR)
  AND premio_emitido_cap IS NOT NULL AND premio_emitido_cap != 0
GROUP BY 1, 2
ORDER BY premio_cap_total DESC
LIMIT 20
```

## Query 4

_5 linha(s), 15.2 MiB processados_

```sql
-- Q4: Capitalização/Previdência - evolução anual do mercado total
SELECT
  EXTRACT(YEAR FROM periodo_ref) AS ano,
  SUM(premio_emitido_cap) AS premio_cap,
  SUM(sinistros_ocorridos_cap) AS sinistros_cap,
  SUM(recuperacao_sinistros_ocorridos_cap) AS recuperacao_cap,
  SAFE_DIVIDE(SUM(sinistros_ocorridos_cap), SUM(premio_emitido_cap)) AS lr_cap,
  COUNT(DISTINCT entity_code) AS n_entidades
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE_SUB(DATE '2026-02-01', INTERVAL 4 YEAR)
  AND premio_emitido_cap IS NOT NULL AND premio_emitido_cap != 0
GROUP BY 1
ORDER BY 1
```

## Query 5

_14 linha(s), 21.3 MiB processados_

```sql
-- Q5: Sub-ramos de Pessoas Individual (13) - breakdown detalhado
SELECT
  branch_code,
  branch_name,
  SUM(premio_direto) AS premio_direto,
  SUM(premio_ganho) AS premio_ganho,
  SUM(sinistro_ocorrido) AS sinistro_ocorrido,
  SUM(desp_com) AS desp_com,
  SAFE_DIVIDE(SUM(sinistro_ocorrido), SUM(premio_ganho)) AS loss_ratio,
  SAFE_DIVIDE(SUM(desp_com), SUM(premio_ganho)) AS expense_ratio
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE_SUB(DATE '2026-02-01', INTERVAL 3 YEAR)
  AND ramo_group_code = '13'
GROUP BY 1, 2
ORDER BY premio_direto DESC
```

## Query 6

_10 linha(s), 11.8 MiB processados_

```sql
-- Q6: Capitalização/Previdência - top 5 players YoY 2023→2024→2025 (full years)
SELECT
  entity_name,
  economic_group_name,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2023 THEN premio_emitido_cap ELSE 0 END) AS cap_2023,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2024 THEN premio_emitido_cap ELSE 0 END) AS cap_2024,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2025 THEN premio_emitido_cap ELSE 0 END) AS cap_2025,
  SAFE_DIVIDE(
    SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2025 THEN premio_emitido_cap ELSE 0 END)
    - SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2024 THEN premio_emitido_cap ELSE 0 END),
    SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2024 THEN premio_emitido_cap ELSE 0 END)
  ) AS var_pct_2425
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE '2023-01-01' AND periodo_ref <= DATE '2025-12-01'
  AND premio_emitido_cap IS NOT NULL AND premio_emitido_cap != 0
GROUP BY 1, 2
ORDER BY cap_2025 DESC
LIMIT 10
```

## Query 7

_15 linha(s), 22.1 MiB processados_

```sql
-- Q7: Prestamista (1377) - evolução anual e top players
SELECT
  entity_name,
  economic_group_name,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2023 THEN premio_direto ELSE 0 END) AS prem_2023,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2024 THEN premio_direto ELSE 0 END) AS prem_2024,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2025 THEN premio_direto ELSE 0 END) AS prem_2025,
  SUM(premio_direto) AS prem_total,
  SUM(sinistro_ocorrido) AS sinistro_total,
  SUM(desp_com) AS comissao_total,
  SAFE_DIVIDE(SUM(sinistro_ocorrido), SUM(premio_ganho)) AS loss_ratio,
  SAFE_DIVIDE(SUM(desp_com), SUM(premio_ganho)) AS expense_ratio
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE_SUB(DATE '2026-02-01', INTERVAL 3 YEAR)
  AND branch_code = '1377'
GROUP BY 1, 2
ORDER BY prem_total DESC
LIMIT 15
```

## Query 8

_24 linha(s), 2.9 MiB processados_

```sql
-- Q8: Previdência/Cap mensal 2024 vs 2025 - verificar se é queda real ou lag
SELECT
  FORMAT_DATE('%Y-%m', periodo_ref) AS mes,
  SUM(premio_emitido_cap) AS premio_cap_total
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE '2024-01-01' AND periodo_ref <= DATE '2025-12-01'
  AND premio_emitido_cap IS NOT NULL AND premio_emitido_cap != 0
GROUP BY 1
ORDER BY 1
```

## Query 9

_12 linha(s), 19.1 MiB processados_

```sql
-- Q9: Seguro Viagem (1369) - top players e evolução anual
SELECT
  entity_name,
  economic_group_name,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2023 THEN premio_direto ELSE 0 END) AS prem_2023,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2024 THEN premio_direto ELSE 0 END) AS prem_2024,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2025 THEN premio_direto ELSE 0 END) AS prem_2025,
  SUM(sinistro_ocorrido) AS sinistro_total,
  SUM(premio_ganho) AS premio_ganho_total,
  SAFE_DIVIDE(SUM(sinistro_ocorrido), SUM(premio_ganho)) AS loss_ratio
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE_SUB(DATE '2026-02-01', INTERVAL 3 YEAR)
  AND branch_code = '1369'
GROUP BY 1, 2
ORDER BY prem_2025 DESC
LIMIT 12
```

## Query 10

_2 linha(s), 23.1 MiB processados_

```sql
-- Q10: FACTA Seguradora - perfil completo por ramo_group
SELECT
  ramo_group_code,
  ramo_group_name,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2023 THEN premio_direto ELSE 0 END) AS prem_2023,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2024 THEN premio_direto ELSE 0 END) AS prem_2024,
  SUM(CASE WHEN EXTRACT(YEAR FROM periodo_ref) = 2025 THEN premio_direto ELSE 0 END) AS prem_2025,
  SUM(desp_com) AS comissao_total,
  SUM(premio_ganho) AS premio_ganho_total,
  SAFE_DIVIDE(SUM(sinistro_ocorrido), SUM(premio_ganho)) AS loss_ratio,
  SAFE_DIVIDE(SUM(desp_com), SUM(premio_ganho)) AS expense_ratio
FROM `susep_ses_marts.fct_seguros`
WHERE periodo_ref >= DATE_SUB(DATE '2026-02-01', INTERVAL 3 YEAR)
  AND entity_name = 'FACTA SEGURADORA S.A.'
GROUP BY 1, 2
ORDER BY prem_2025 DESC
```
