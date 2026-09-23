import json
from typing import Any

from evals.precisao.score import (
    answer_path,
    extract_answer,
    names_match,
    normalize_month,
    score_percent,
    score_ranking,
    score_run,
    score_value,
    summarize,
    trap_hits,
)

TRUTH: dict[str, Any] = {
    "snapshot": "2026-09-21",
    "snapshots_k": 13,
    "questions": {
        "q1": {"kind": "valor", "text": "t1", "trap": "x", "answer": {"valor": "1000000.00"}},
        "q2": {
            "kind": "mes_valor",
            "text": "t2",
            "trap": "x",
            "answer": {"mes": "2026-07", "valor": "500.00"},
        },
        "q4": {
            "kind": "ranking",
            "text": "t4",
            "trap": "x",
            "answer": {
                "ranking": [
                    {
                        "codigo": "05631",
                        "nome": "BRASILPREV SEGUROS E PREVIDÊNCIA S/A.",
                        "valor": "300",
                    },
                    {
                        "codigo": "06866",
                        "nome": "PORTO SEGURO COMPANHIA DE SEGUROS GERAIS",
                        "valor": "200",
                    },
                ]
            },
        },
        "q5": {"kind": "percentual", "text": "t5", "trap": "x", "answer": {"percentual": "5.25"}},
    },
    "diagnostics": {"q1_todos_snapshots_razao": 12.97, "q1_sem_trocar_virgula_razao": 0.79},
}


def _run(
    arm: str, qid: str, answer: dict[str, Any] | None, cost: float, **extra: Any
) -> dict[str, Any]:
    return {
        "run_id": f"{arm}-{qid}-r1",
        "arm": arm,
        "arm_label": f"braço {arm}",
        "question": qid,
        "rep": 1,
        "status": "ok",
        "answer": answer,
        "cost_usd": cost,
        "num_turns": 4,
        "queries": [{"query_no": 1, "status": "ok", "bytes_estimated": 1024, "sql": "SELECT 1"}],
        "skill_calls": [],
        "started_at": "2026-09-22T10:00:00+00:00",
        **extra,
    }


def test_value_within_tolerance_is_correct() -> None:
    score = score_value(1_004_000.0, "1000000")
    assert score.correct
    assert score.label == "certo"


def test_value_summed_over_every_snapshot_is_labeled() -> None:
    assert score_value(12_970_000.0, "1000000").label == "snapshot_duplicado"


def test_value_that_lost_the_decimals_is_an_undercount() -> None:
    score = score_value(790_000.0, "1000000")
    assert not score.correct
    assert score.label == "subcontagem"


def test_value_in_the_wrong_unit_is_a_scale_error() -> None:
    assert score_value(0.001, "1000000").label == "escala_errada"


def test_missing_or_non_numeric_value_has_no_answer() -> None:
    assert score_value(None, "1").label == "sem_resposta"
    assert score_value(True, "1").label == "sem_resposta"
    assert score_value("1000000", "1000000").label == "sem_resposta"


def test_normalize_month_accepts_numeric_forms() -> None:
    assert normalize_month("2026-07") == "2026-07"
    assert normalize_month("202607") == "2026-07"
    assert normalize_month("07/2026") == "2026-07"
    assert normalize_month("julho") is None
    assert normalize_month(None) is None


def test_month_value_needs_the_right_month() -> None:
    wrong = score_run(
        _run("A", "q2", {"mes_referencia": "2026-06", "valor_reais": 500.0}, 0.1), TRUTH
    )
    right = score_run(
        _run("A", "q2", {"mes_referencia": "2026-07", "valor_reais": 500.0}, 0.1), TRUTH
    )
    assert wrong.label == "mes_errado"
    assert right.correct


def test_percent_tolerance_and_scale() -> None:
    assert score_percent(5.3, "5.25").correct
    assert score_percent(0.0525, "5.25").label == "escala_errada"
    assert score_percent(7.0, "5.25").label == "valor_errado"


def test_names_match_accepts_short_forms_and_rejects_other_companies() -> None:
    official = "PORTO SEGURO COMPANHIA DE SEGUROS GERAIS"
    assert names_match("Porto Seguro", official)
    assert names_match("PORTO SEGURO CIA DE SEGUROS GERAIS", official)
    assert names_match("Brasilprev", "BRASILPREV SEGUROS E PREVIDÊNCIA S/A.")
    assert not names_match("Bradesco Vida e Previdência", "BRASILPREV SEGUROS E PREVIDÊNCIA S/A.")
    assert not names_match("S.A.", official)


def test_ranking_accepts_short_names_and_dropped_leading_zeros() -> None:
    given = [
        {"codigo": "5631", "nome": "Brasilprev", "valor_reais": 300.0},
        {"codigo": "06866", "nome": "Porto Seguro", "valor_reais": 200.5},
    ]
    score = score_ranking(given, TRUTH["questions"]["q4"]["answer"]["ranking"])
    assert score.correct
    assert score.names_ok


def test_ranking_with_an_inferred_name_is_wrong() -> None:
    given = [
        {"codigo": "05631", "nome": "Bradesco Vida e Previdência", "valor_reais": 300.0},
        {"codigo": "06866", "nome": "Porto Seguro", "valor_reais": 200.0},
    ]
    score = score_ranking(given, TRUTH["questions"]["q4"]["answer"]["ranking"])
    assert not score.correct
    assert score.label == "nome_inventado"


def test_ranking_in_the_wrong_order() -> None:
    given = [
        {"codigo": "06866", "nome": "Porto Seguro", "valor_reais": 200.0},
        {"codigo": "05631", "nome": "Brasilprev", "valor_reais": 300.0},
    ]
    score = score_ranking(given, TRUTH["questions"]["q4"]["answer"]["ranking"])
    assert score.label == "ordem_errada"


def test_runs_without_an_answer_are_labeled_by_cause() -> None:
    crashed = _run("A", "q1", None, 0.0, status="crash")
    out_of_turns = _run("A", "q1", None, 0.9, result_subtype="error_max_turns")
    assert score_run(crashed, TRUTH).label == "falha"
    assert score_run(out_of_turns, TRUTH).label == "limite_de_turnos"


def test_extract_answer_prefers_structured_output() -> None:
    assert extract_answer({"valor_reais": 1}, ['```json\n{"valor_reais": 2}\n```']) == (
        {"valor_reais": 1},
        "structured",
    )
    assert extract_answer('{"valor_reais": 3}', []) == ({"valor_reais": 3}, "structured")
    assert extract_answer(None, ["texto", '```json\n{"valor_reais": 2}\n```']) == (
        {"valor_reais": 2},
        "text",
    )
    assert extract_answer(None, ["sem json"]) == (None, "none")


def test_summarize_reports_cost_per_correct_answer_deterministically() -> None:
    runs = [
        _run("A", "q1", {"valor_reais": 12_970_000.0}, 0.50),
        _run("A", "q5", {"variacao_percentual": 5.25}, 0.30),
        _run("C", "q1", {"valor_reais": 1_000_000.0}, 0.10),
        _run("C", "q5", {"variacao_percentual": 5.2}, 0.10),
    ]
    first = summarize(runs, TRUTH)
    second = summarize(runs, TRUTH)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    arm_a, arm_c = first["bracos"]["A"], first["bracos"]["C"]
    assert arm_a["certos"] == 1
    assert arm_a["erros"] == {"snapshot_duplicado": 1}
    assert arm_c["certos"] == 2
    assert arm_c["custo_por_certo_usd"] == arm_c["custo_total_usd"] / 2
    assert arm_a["por_pergunta"]["q5"] == {"certos": 1, "runs": 1, "sem_filtrar": 0}


def test_trap_hits_catch_shortcuts_even_when_the_answer_is_right() -> None:
    run = _run("A", "q1", {"valor_reais": 1_000_000.0}, 0.2)
    run["queries"] = [
        {
            "query_no": 1,
            "status": "ok",
            "sql": "SELECT SUM(CAST(REPLACE(premio_direto, ',', '.') AS FLOAT64)) "
            "FROM `b.ses_seguros` WHERE damesano LIKE '2024%'",
        },
        {
            "query_no": 2,
            "status": "ok",
            "sql": "SELECT SUM(SAFE_CAST(premio_direto AS NUMERIC)) FROM b.ses_seguros "
            "WHERE _ingestion_date = '2026-09-21'",
        },
        {
            "query_no": 3,
            "status": "rejected",
            "sql": "SELECT SUM(premio_direto) FROM b.ses_seguros",
        },
    ]
    q3 = _run("A", "q3", None, 0.1)
    q3["queries"] = [{"status": "ok", "sql": "SELECT SUM(x) FROM t WHERE cogrupo = '05'"}]

    assert trap_hits(run) == ["converteu_sem_trocar_a_virgula", "somou_todos_os_snapshots"]
    assert trap_hits(q3) == ["usou_cogrupo_como_ramo"]
    assert score_run(run, TRUTH).correct
    summary = summarize([run], TRUTH)["bracos"]["A"]
    assert summary["certos_depois_de_tropecar"] == 1


_UNFILTERED = "SELECT SUM(x) FROM b.ses_seguros WHERE damesano LIKE '2024%'"
_FILTERED = "SELECT SUM(x) FROM b.ses_seguros WHERE _ingestion_date = (SELECT MAX(_ingestion_date))"


def _path(answer: dict[str, Any], sqls: list[str], qid: str = "q1") -> str:
    run = _run("A", qid, answer, 0.1)
    run["queries"] = [
        {"query_no": i, "status": "ok", "sql": sql} for i, sql in enumerate(sqls, start=1)
    ]
    return answer_path(run, score_run(run, TRUTH))


def test_answer_path_tells_luck_from_correction() -> None:
    right = {"valor_reais": 1_000_000.0}
    assert _path({**right, "queries_usadas": [1]}, [_UNFILTERED]) == "certo_sem_filtrar"
    assert _path({**right, "queries_usadas": [2]}, [_UNFILTERED, _FILTERED]) == "certo_corrigindo"
    assert _path({**right, "queries_usadas": [1]}, [_FILTERED]) == "certo_limpo"
    # Sem citação, vale a última soma executada.
    assert _path(right, [_FILTERED, _UNFILTERED]) == "certo_sem_filtrar"
    assert _path({"valor_reais": 13_000_000.0}, [_UNFILTERED]) == "errado"


def test_summary_counts_paths_per_arm_and_question() -> None:
    lucky = _run("A", "q5", {"variacao_percentual": 5.25, "queries_usadas": [1]}, 0.1)
    lucky["queries"] = [{"query_no": 1, "status": "ok", "sql": _UNFILTERED}]
    arm = summarize([lucky], TRUTH)["bracos"]["A"]
    assert arm["caminhos"]["certo_sem_filtrar"] == 1
    assert arm["por_pergunta"]["q5"]["sem_filtrar"] == 1


def test_summarize_has_no_cost_per_correct_when_nothing_is_right() -> None:
    summary = summarize([_run("A", "q1", {"valor_reais": 5.0}, 0.2)], TRUTH)
    assert summary["bracos"]["A"]["custo_por_certo_usd"] is None
