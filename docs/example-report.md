---
date: 2026-06-09
model: claude-sonnet-4-6
ingestion_date_covered: null
queries_run: 10
cost_usd: 0.4773
queries_file: queries/2026-06-09.sql.md
generated_by: susep-insights-agent
---

# Insights SUSEP SES — 2026-06-09
## Sumário executivo

**Modo: novo ângulo**

O relatório de hoje abre um mercado inteiramente inexplorado nos reports anteriores: a previdência privada (PGBL/VGBL) reportada no campo `premio_emitido_cap` do SES, que movimentou R$ 194 bi em 2024 — volume equivalente a **todo o mercado de seguros convencional** — e contraiu -18,7% em 2025, com a queda concentrada no segundo semestre. Como segundo ângulo, mapeia o ramo Prestamista (1377), onde a sinistralidade é de apenas 7,4% mas 64% do prêmio ganho é consumido em comissões, e rastreia a expansão multi-ramo da FACTA Seguradora, cujo modelo replica a equação de baixíssima sinistralidade e altíssima comissão em dois segmentos simultaneamente.

---

## Insights

### 1. O mercado invisível: previdência privada supera todo o seguro convencional — e nunca apareceu neste relatório

O campo `premio_emitido_cap` contém as contribuições de previdência privada (PGBL/VGBL) reguladas pela SUSEP. Em 2024, o mercado total atingiu **R$ 194,3 bi** — praticamente idêntico ao prêmio direto somado de todos os ramos convencionais (R$ ~196 bi/ano na média dos últimos 3 anos). São 27–29 entidades operando, com estrutura fortemente bancária: BRADESCO VIDA (R$ 50,0 bi em 2024), BRASILPREV/BB (R$ 56,1 bi) e CAIXA VIDA (R$ 25,9 bi) respondem pelos três maiores blocos. A sinistralidade do segmento é irrisória — a LR média é de 0,5% (apenas resgates por morte ou invalidez no SES), pois resgates por vencimento transitam por outros canais contábeis. _(Queries 3, 4)_

---

### 2. Queda sistêmica de R$ 36 bi: previdência contrai -18,7% em 2025

Após dois anos de crescimento contínuo (+18,8% em 2023 e +16,9% em 2024), o mercado de previdência reverteu em 2025: **R$ 158 bi, versus R$ 194,3 bi em 2024 (-18,7%, queda de R$ 36,4 bi)**. A queda não é artefato de dados: a série mensal confirma que o primeiro semestre de 2025 ainda sustentava uma média de R$ 14,8 bi/mês (próxima dos R$ 16,2 bi de 2024), mas o segundo semestre colapsou. A média mensal de agosto a dezembro de 2025 foi de **R$ 10,8 bi** — contra R$ 16,5 bi no mesmo período de 2024, uma retração de -33%. Junho 2025 registrou o piso do ciclo: R$ 8,7 bi, o menor nível desde antes de 2023. _(Queries 4, 8)_

---

### 3. Os maiores perdedores: ITAÚ -33%, BRASILPREV -25%, ZURICH SANTANDER -30%

A contração de 2025 é generalizada entre os grandes, com intensidade distinta. **ITAÚ VIDA** sofreu a maior queda proporcional entre os líderes: de R$ 21,6 bi para R$ 14,5 bi (**-33,0%**). **ZURICH SANTANDER** recuou de R$ 16,4 bi para R$ 11,4 bi (**-30,3%**). **BRASILPREV** (o maior player absoluto) caiu de R$ 56,1 bi para R$ 42,0 bi (**-25,1%**). **BRADESCO VIDA** também recuou de R$ 50,0 bi para R$ 42,9 bi (-14,4%). A exceção estrutural é a **CAIXA VIDA**, que praticamente manteve o volume (R$ 25,9 bi → R$ 25,7 bi, -1,0%), e a **PRUDENTIAL DO BRASIL**, que saiu de R$ 1,0 bi para R$ 6,3 bi em 2025 (**+519%**) — única disrupção relevante no ranking. _(Query 6)_

---

### 4. Prestamista (1377): o ramo mais lucrativo do Brasil — para o distribuidor, não para a seguradora

Com R$ 5,9 bi em prêmios diretos nos últimos 3 anos, o ramo Prestamista (seguro vinculado a crédito bancário) exibe a **menor sinistralidade do mercado: LR de 7,4%** — apenas R$ 326 mi em sinistros sobre R$ 5,9 bi de prêmio. Mas o expense ratio de **64,3%** (comissões sobre prêmio ganho) absorve quase todo o valor técnico restante. O combined ratio resultante de ~71,7% deixa a seguradora lucrativa, mas a maior fatia econômica do produto vai ao banco distribuidor. O segmento está em forte crescimento: **CARDIF** lidera com R$ 1,26 bi acumulados (2025: R$ 459 mi, +52% vs 2023), **METROPOLITAN LIFE** mais que triplicou de R$ 138 mi para R$ 504 mi em 2025 (+265%), e novas entrantes como KOVR SEGURADORA operam com LR de apenas 1,2% — praticamente nenhum sinistro em três anos. _(Queries 5, 7)_

---

### 5. FACTA Seguradora: o modelo de fábrica de comissões escalando para o segundo ramo

A FACTA, identificada no relatório de 22/05 como epicentro do expense ratio de Microsseguros, executou em 2025 uma replicação fiel do modelo em Prestamista. A empresa entrou no ramo Prestamista **do zero para R$ 761 mi em um único ano** (2025), com expense ratio de 76,9% e LR de 13,9%. Ao mesmo tempo, o Microsseguros continuou gerando R$ 778 mi, com expense ratio de 73,2% e LR de 4,1%. **Total FACTA em 2025: ~R$ 1,54 bi** — ante R$ 453 mi em 2023 (+240% em dois anos). O padrão é idêntico em ambos os ramos: sinistralidade mínima (produto de cobrança bancária com poucos acionamentos) e comissão máxima (produto vendido em escala pelo distribuidor financeiro). A FACTA não está construindo capacidade técnica — está construindo escala de distribuição. _(Queries 7, 10)_

---

### 6. Seguro Viagem: AIG no déficit técnico com LR de 107% — Porto Seguro lucra com 33%

O ramo Viagem (1369) cresceu para ~R$ 900 mi de prêmio direto em 2025, impulsionado pela normalização do turismo internacional pós-pandemia. Mas a distribuição técnica entre players é extrema. **AIG SEGUROS**, a maior do ramo em 2025 (R$ 133 mi), opera com **LR de 107%** — os sinistros superaram os prêmios ganhos em R$ 30 mi nos 3 anos. **GENERALI** (R$ 60 mi em 2025) está em LR de 86%, e **AXA** (R$ 18 mi, em retração) em 89%. No polo oposto, **PORTO SEGURO** cresceu de R$ 97 mi para R$ 131 mi em 2025 com **LR de 33%** — operando na mesma praia com rentabilidade técnica tripla. Destaque para a **IZA SEGURADORA**, nova entrante: saiu de zero em 2023 para R$ 56 mi em 2025 com LR de 65%. A bifurcação de 74 p.p. entre o pior (AIG, 107%) e o melhor (Porto Seguro, 33%) no mesmo ramo evidencia que produto, seleção de risco e precificação fazem toda a diferença em Viagem. _(Query 9)_
