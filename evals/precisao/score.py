"""Pontua os runs contra o gabarito e resume por braço.

    uv run python -m evals.precisao.score evals/precisao/results/full \\
        --truth evals/precisao/results/truth.json

Grava summary.json (lido pelos slides), summary.md e summary.csv no diretório
dos resultados. A pontuação é determinística: rodar de novo sobre o mesmo
runs.jsonl dá o mesmo resumo.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# 0,5% pega soma de vários snapshots, grupo errado e decimal perdido, e ainda
# perdoa arredondamento na resposta.
VALUE_REL_TOL = 0.005
PCT_ABS_TOL = 0.1  # pontos percentuais
WORD_SIMILARITY = 0.85
BQ_USD_PER_TIB = 6.25  # BigQuery on-demand, preço de lista
_TIB = 1024**4

# Palavras que não identificam uma empresa: ficam fora da conferência de nome.
_NAME_STOPWORDS = frozenset(
    {"S", "A", "SA", "DE", "DA", "DO", "DOS", "DAS", "E", "CIA", "COMPANHIA", "LTDA"}
)
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_MONTH_YM = re.compile(r"(\d{4})\D?(\d{2})")
_MONTH_MY = re.compile(r"(\d{2})\D(\d{4})")

_NO_ANSWER_LABELS = {
    "error_max_turns": "limite_de_turnos",
    "error_max_budget_usd": "limite_de_orcamento",
}


@dataclass(frozen=True)
class Score:
    correct: bool
    label: str  # "certo" ou o tipo de erro
    erro: float | None = None  # relativo para valores, em p.p. para percentuais
    names_ok: bool | None = None


# --- Extração da resposta --------------------------------------------------


def extract_answer(structured: Any, texts: list[str]) -> tuple[dict[str, Any] | None, str]:
    """The run's answer and where it came from: 'structured', 'text' or 'none'."""
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except json.JSONDecodeError:
            structured = None
    if isinstance(structured, dict):
        return structured, "structured"
    for block in reversed(_JSON_BLOCK.findall("\n".join(texts))):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj, "text"
    return None, "none"


# --- Normalização ----------------------------------------------------------


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", text.upper()).split())


def names_match(given: str, official: str) -> bool:
    """True when every significant word of ``given`` is in the official name.

    Accepts short forms ("Porto Seguro" for "PORTO SEGURO COMPANHIA DE SEGUROS
    GERAIS") and rejects a different company's name, which is what an inferred
    name looks like.
    """
    official_words = set(normalize_name(official).split())
    given_words = [w for w in normalize_name(given).split() if w not in _NAME_STOPWORDS]
    if not given_words or not official_words:
        return False
    return all(
        w in official_words
        or any(SequenceMatcher(None, w, o).ratio() >= WORD_SIMILARITY for o in official_words)
        for w in given_words
    )


def normalize_month(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    if m := _MONTH_YM.search(text):
        return f"{m.group(1)}-{m.group(2)}"
    if m := _MONTH_MY.search(text):
        return f"{m.group(2)}-{m.group(1)}"
    return None


def normalize_code(code: Any) -> str:
    return str(code).strip().lstrip("0")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


# --- Pontuação -------------------------------------------------------------


def value_error_label(given: float, truth: float) -> str:
    """Name the likely mistake behind a wrong value."""
    for scale in (1e3, 1e6, 1e9):
        if abs(given * scale - truth) / abs(truth) <= VALUE_REL_TOL:
            return "escala_errada"
    ratio = given / truth
    k = round(ratio)
    if k >= 2 and abs(ratio - k) / k <= 0.02:
        return "snapshot_duplicado"
    return "sobrecontagem" if ratio > 1 else "subcontagem"


def score_value(given: Any, truth: Decimal | str) -> Score:
    value = _number(given)
    if value is None:
        return Score(False, "sem_resposta")
    t = float(truth)
    err = abs(value - t) / abs(t)
    if err <= VALUE_REL_TOL:
        return Score(True, "certo", err)
    return Score(False, value_error_label(value, t), err)


def score_month_value(answer: dict[str, Any], truth: dict[str, Any]) -> Score:
    if normalize_month(answer.get("mes_referencia")) != truth["mes"]:
        value = score_value(answer.get("valor_reais"), truth["valor"])
        return Score(False, "mes_errado", value.erro)
    return score_value(answer.get("valor_reais"), truth["valor"])


def score_percent(given: Any, truth: Decimal | str) -> Score:
    value = _number(given)
    if value is None:
        return Score(False, "sem_resposta")
    t = float(truth)
    err = abs(value - t)
    if err <= PCT_ABS_TOL:
        return Score(True, "certo", err)
    if abs(value * 100 - t) <= PCT_ABS_TOL:
        return Score(False, "escala_errada", err)
    return Score(False, "valor_errado", err)


def score_ranking(given: Any, truth: list[dict[str, Any]]) -> Score:
    if not isinstance(given, list) or len(given) < len(truth):
        return Score(False, "sem_resposta")
    pairs = list(zip(given, truth, strict=False))
    try:
        codes = [normalize_code(g["codigo"]) for g, _ in pairs]
        values = [_number(g["valor_reais"]) for g, _ in pairs]
        names = [str(g["nome"]) for g, _ in pairs]
    except (KeyError, TypeError):
        return Score(False, "sem_resposta")

    truth_codes = [normalize_code(t["codigo"]) for t in truth]
    names_ok = all(names_match(n, t["nome"] or "") for n, t in zip(names, truth, strict=False))
    errors = [
        abs(v - float(t["valor"])) / abs(float(t["valor"])) if v is not None else float("inf")
        for v, t in zip(values, truth, strict=False)
    ]
    worst = max(errors)
    worst_out = None if worst == float("inf") else worst

    if codes != truth_codes:
        label = "ordem_errada" if set(codes) == set(truth_codes) else "ranking_errado"
        return Score(False, label, worst_out, names_ok)
    if worst > VALUE_REL_TOL:
        i = errors.index(worst)
        v = values[i]
        label = "sem_resposta" if v is None else value_error_label(v, float(truth[i]["valor"]))
        return Score(False, label, worst_out, names_ok)
    if not names_ok:
        return Score(False, "nome_inventado", worst_out, names_ok)
    return Score(True, "certo", worst_out, names_ok)


def score_run(run: dict[str, Any], truth: dict[str, Any]) -> Score:
    if run.get("status") != "ok":
        return Score(False, "falha")
    answer = run.get("answer")
    if not isinstance(answer, dict):
        return Score(False, _NO_ANSWER_LABELS.get(run.get("result_subtype") or "", "sem_resposta"))

    question = truth["questions"][run["question"]]
    kind, expected = question["kind"], question["answer"]
    if kind == "valor":
        return score_value(answer.get("valor_reais"), expected["valor"])
    if kind == "mes_valor":
        return score_month_value(answer, expected)
    if kind == "ranking":
        return score_ranking(answer.get("ranking"), expected["ranking"])
    return score_percent(answer.get("variacao_percentual"), expected["percentual"])


# --- Custo -----------------------------------------------------------------


def tokens(run: dict[str, Any]) -> tuple[int, int]:
    """(input incl. cache reads and writes, output) tokens of a run."""
    usage = run.get("usage") or {}
    inp = sum(
        int(usage.get(k) or 0)
        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    return inp, int(usage.get("output_tokens") or 0)


# Tipos de token como o SDK registra no model_usage, com o nome usado no resumo.
_TOKEN_TYPES = (
    ("inputTokens", "entrada"),
    ("cacheCreationInputTokens", "cache_escrita"),
    ("cacheReadInputTokens", "cache_leitura"),
    ("outputTokens", "saida"),
)
_USAGE_KEYS = {
    "inputTokens": "input_tokens",
    "cacheCreationInputTokens": "cache_creation_input_tokens",
    "cacheReadInputTokens": "cache_read_input_tokens",
    "outputTokens": "output_tokens",
}


def usage_by_model(run: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Tokens by type and cost per model the run called.

    The SDK's model_usage lists every model, including the small auxiliary call
    Claude Code makes on its own; the top-level usage covers only the agent's
    model and is the fallback for records without model_usage.
    """
    by_model = run.get("model_usage") or {}
    if not by_model and run.get("usage"):
        usage = run["usage"]
        by_model = {
            str(run.get("model_resolved") or "?"): {
                **{k: usage.get(v) or 0 for k, v in _USAGE_KEYS.items()},
                "costUSD": run.get("cost_usd") or 0,
            }
        }
    return {
        model: {
            **{name: float(u.get(key) or 0) for key, name in _TOKEN_TYPES},
            "custo_usd": float(u.get("costUSD") or 0),
        }
        for model, u in by_model.items()
    }


def _add_usage(total: dict[str, dict[str, float]], run: dict[str, Any]) -> None:
    for model, usage in usage_by_model(run).items():
        acc = total.setdefault(model, {"runs": 0.0})
        acc["runs"] += 1
        for key, value in usage.items():
            acc[key] = acc.get(key, 0.0) + value


def token_totals(by_model: dict[str, dict[str, float]]) -> dict[str, float]:
    """Tokens by type across models, plus the grand total."""
    totals = {name: sum(u.get(name, 0.0) for u in by_model.values()) for _, name in _TOKEN_TYPES}
    totals["total"] = sum(totals.values())
    return totals


def bq_bytes(run: dict[str, Any]) -> int:
    """Bytes the executed queries read, from the cache-free dry-run estimate."""
    return sum(
        int(q.get("bytes_estimated") or 0) for q in run.get("queries", []) if q["status"] == "ok"
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


# --- Tropeços no caminho ---------------------------------------------------
# Um run pode acertar no fim depois de cair numa armadilha no meio. Estas
# heurísticas olham o SQL executado (e, no CSV, os erros do DuckDB); servem
# para contar a história, e cada caso vale conferir no transcript.
_SUM = re.compile(r"\bsum\s*\(")
_RAW_CAST = re.compile(r"(?:safe_)?cast\s*\(\s*premio_\w+\s+as\b")
_COGRUPO_FILTER = re.compile(r"\bcogrupo\s*(?:=|in\b|like\b)")
# Registros antigos não têm "layer"; a camada sai do braço.
_LAYER_BY_ARM = {"A": "bronze", "B": "bronze", "C": "marts", "D": "csv"}
# Erros do DuckDB que denunciam cada armadilha do arquivo cru.
_CSV_ERROR_TRAPS = (
    ("encoding_errado", re.compile(r"unicode|not latin-1 encoded|does not support the encoding")),
    ("tipo_inferido_errado", re.compile(r"this type was auto-detected")),
    ("somou_coluna_de_texto", re.compile(r"sum\(varchar\)")),
    ("converteu_sem_trocar_a_virgula", re.compile(r"could not convert string '[^']*,")),
)
# read_csv('<arquivo>', ..., ignore_errors=true): o DuckDB descarta em silêncio as
# linhas que não consegue ler. Nos cadastros (Windows-1252) são 29% das linhas.
_IGNORE_ERRORS_READ = re.compile(r"read_csv\s*\(\s*'([^']+)'[^)]*?ignore_errors\s*=\s*true")
_CSV_FACT = "ses_seguros.csv"


def layer_of(run: dict[str, Any]) -> str:
    return str(run.get("layer") or _LAYER_BY_ARM.get(str(run.get("arm")), "bronze"))


def _sums_every_snapshot(sql: str) -> bool:
    low = sql.lower()
    return "ses_seguros" in low and bool(_SUM.search(low)) and "_ingestion_date" not in low


def trap_hits(run: dict[str, Any]) -> list[str]:
    """Traps the run's queries fell into, even if the final answer was right.

    The snapshot trap only exists in bronze: a CSV from the zip is one load.
    """
    layer = layer_of(run)
    hits: set[str] = set()
    for q in run.get("queries", []):
        sql = q["sql"].lower()
        if q["status"] == "ok":
            if layer == "bronze" and _sums_every_snapshot(sql):
                hits.add("somou_todos_os_snapshots")
            if layer != "marts" and _RAW_CAST.search(sql):
                hits.add("converteu_sem_trocar_a_virgula")
            if run["question"] == "q3" and _COGRUPO_FILTER.search(sql):
                hits.add("usou_cogrupo_como_ramo")
            if layer == "csv" and _drops_cadastro_rows(sql):
                hits.add("descartou_linhas_com_ignore_errors")
        elif q["status"] == "error" and layer == "csv":
            error = (q.get("error") or "").lower()
            hits.update(name for name, pattern in _CSV_ERROR_TRAPS if pattern.search(error))
    return sorted(hits)


def _drops_cadastro_rows(sql: str) -> bool:
    """A lookup CSV read with ignore_errors, which silently drops rows."""
    return any(
        Path(name).name.lower() != _CSV_FACT for name in _IGNORE_ERRORS_READ.findall(sql.lower())
    )


def answer_path(run: dict[str, Any], score: Score) -> str:
    """How a run got to its answer, not just whether the answer matched.

    * ``errado``: the answer did not match.
    * ``certo_por_sorte``: right, but only because of how this data happens to
      be. In bronze, every aggregate the answer cites summed all loads (the
      inflation cancels in a ratio, or the period exists in one load only). In
      the CSV arm, the aggregate the answer cites joins a lookup file read with
      ignore_errors, which silently drops the rows it can't decode.
    * ``certo_corrigindo``: fell into a trap on the way (bronze: summed all
      loads; CSV: encoding, type or decimal comma) but the answer rests on
      queries that got past it.
    * ``certo_limpo``: never fell into a trap.
    """
    if not score.correct:
        return "errado"
    ok = {q["query_no"]: q for q in run.get("queries", []) if q["status"] == "ok"}
    answer = run.get("answer") or {}
    if layer_of(run) == "csv":
        cited = [ok[n] for n in answer.get("queries_usadas") or [] if n in ok]
        if not cited and ok:
            cited = [ok[max(ok)]]
        # Sorte só quando a query que soma também junta o cadastro com perdas;
        # uma listagem à parte, só para contexto, não muda o número.
        if any(_SUM.search(q["sql"].lower()) and _drops_cadastro_rows(q["sql"]) for q in cited):
            return "certo_por_sorte"
        return "certo_corrigindo" if trap_hits(run) else "certo_limpo"
    sums = {n: q for n, q in ok.items() if _SUM.search(q["sql"].lower())}
    cited_sums = [n for n in answer.get("queries_usadas") or [] if n in sums]
    if not cited_sums and sums:
        cited_sums = [max(sums)]
    if cited_sums and all(_sums_every_snapshot(sums[n]["sql"]) for n in cited_sums):
        return "certo_por_sorte"
    if any(_sums_every_snapshot(q["sql"]) for q in ok.values()):
        return "certo_corrigindo"
    return "certo_limpo"


# --- Resumo ----------------------------------------------------------------


def load_runs(path: Path) -> list[dict[str, Any]]:
    """runs.jsonl, keeping only the last record of each run_id (retries win)."""
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            run = json.loads(line)
            latest[run["run_id"]] = run
    return sorted(latest.values(), key=lambda r: r["run_id"])


def summarize(runs: list[dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
    scored = [(run, score_run(run, truth)) for run in runs]
    arms: dict[str, Any] = {}
    for arm in sorted({run["arm"] for run in runs}):
        rows = [(r, s) for r, s in scored if r["arm"] == arm]
        correct = sum(s.correct for _, s in rows)
        llm = [float(r["cost_usd"]) for r, _ in rows if r.get("cost_usd") is not None]
        bq_usd = [bq_bytes(r) / _TIB * BQ_USD_PER_TIB for r, _ in rows]
        total = sum(llm) + sum(bq_usd)
        tok = [tokens(r) for r, _ in rows]
        arm_usage: dict[str, dict[str, float]] = {}
        for r, _ in rows:
            _add_usage(arm_usage, r)
        arm_tokens = token_totals(arm_usage)
        paths = [(r, s, answer_path(r, s)) for r, s in rows]
        by_question = {
            qid: {
                "certos": sum(s.correct for r, s in rows if r["question"] == qid),
                "runs": sum(1 for r, _ in rows if r["question"] == qid),
                "por_sorte": sum(
                    1 for r, _, p in paths if r["question"] == qid and p == "certo_por_sorte"
                ),
            }
            for qid in truth["questions"]
        }
        arms[arm] = {
            "label": rows[0][0].get("arm_label", arm),
            "camada": layer_of(rows[0][0]),
            "runs": len(rows),
            "certos": correct,
            "acerto": correct / len(rows),
            "por_pergunta": by_question,
            "custo_llm_usd": sum(llm),
            "custo_bq_usd": sum(bq_usd),
            "custo_total_usd": total,
            "custo_medio_usd": total / len(rows),
            "custo_por_certo_usd": total / correct if correct else None,
            "runs_sem_custo": len(rows) - len(llm),
            "tokens_entrada_medio": _mean([float(t[0]) for t in tok]),
            "tokens_saida_medio": _mean([float(t[1]) for t in tok]),
            # Todos os modelos e todos os tipos de token (ver usage_by_model).
            "tokens": arm_tokens,
            "tokens_por_run": arm_tokens["total"] / len(rows),
            "tokens_por_certo": arm_tokens["total"] / correct if correct else None,
            "modelos": arm_usage,
            "turnos_medio": _mean([float(r.get("num_turns") or 0) for r, _ in rows]),
            "queries_medio": _mean([float(len(r.get("queries", []))) for r, _ in rows]),
            "bytes_bq_medio": _mean([float(bq_bytes(r)) for r, _ in rows]),
            "tempo_medio_s": _mean([float(r.get("wall_s") or 0) for r, _ in rows]),
            "queries_barradas": sum(
                1 for r, _ in rows for q in r.get("queries", []) if q["status"] != "ok"
            ),
            "skill_aberta": sum(1 for r, _ in rows if r.get("skill_calls")),
            "erros": dict(sorted(Counter(s.label for _, s in rows if not s.correct).items())),
            "tropecos": dict(sorted(Counter(t for r, _ in rows for t in trap_hits(r)).items())),
            "runs_com_tropeco": sum(1 for r, _ in rows if trap_hits(r)),
            "certos_depois_de_tropecar": sum(1 for r, s in rows if s.correct and trap_hits(r)),
            "caminhos": {
                p: sum(1 for _, _, q in paths if q == p)
                for p in ("certo_limpo", "certo_corrigindo", "certo_por_sorte", "errado")
            },
        }

    started = sorted(r["started_at"] for r in runs if r.get("started_at"))
    all_usage: dict[str, dict[str, float]] = {}
    for r in runs:
        _add_usage(all_usage, r)
    return {
        "meta": {
            "runs": len(runs),
            "modelos": dict(Counter(r.get("model_resolved") or "?" for r in runs)),
            "modelos_uso": all_usage,
            "tokens": token_totals(all_usage),
            "claude_code": dict(
                Counter(str((r.get("init") or {}).get("claude_code_version") or "?") for r in runs)
            ),
            "snapshot": truth["snapshot"],
            "snapshots_k": truth["snapshots_k"],
            "inicio": started[0] if started else None,
            "fim": started[-1] if started else None,
            "tolerancia_valor": VALUE_REL_TOL,
            "tolerancia_pp": PCT_ABS_TOL,
        },
        "perguntas": {
            qid: {"texto": q["text"], "armadilha": q["trap"], "gabarito": q["answer"]}
            for qid, q in truth["questions"].items()
        },
        "diagnosticos": truth["diagnostics"],
        "bracos": arms,
        "runs": [
            {
                "run_id": r["run_id"],
                "arm": r["arm"],
                "question": r["question"],
                "rep": r["rep"],
                "correct": s.correct,
                "label": s.label,
                "erro": s.erro,
                "names_ok": s.names_ok,
                "cost_usd": r.get("cost_usd"),
                "num_turns": r.get("num_turns"),
                "queries": len(r.get("queries", [])),
                "bq_bytes": bq_bytes(r),
                "skill": bool(r.get("skill_calls")),
                "answer_source": r.get("answer_source"),
                "tropecos": ";".join(trap_hits(r)),
                "caminho": answer_path(r, s),
                "tokens": token_totals(usage_by_model(r))["total"],
            }
            for r, s in scored
        ],
    }


def _usd(value: float | None) -> str:
    return "—" if value is None else f"US$ {value:.2f}"


def _num(value: float | None, fmt: str = "{:.0f}") -> str:
    return "—" if value is None else fmt.format(value)


def render_markdown(summary: dict[str, Any]) -> str:
    meta, arms = summary["meta"], summary["bracos"]
    lines = [
        "# Resultado — precisão e custo por camada",
        "",
        f"{meta['runs']} runs, snapshot {meta['snapshot']} ({meta['snapshots_k']} snapshots na "
        f"bronze), modelos: {', '.join(f'{m} ({n})' for m, n in meta['modelos'].items())}.",
        f"Acerto: valor a até {meta['tolerancia_valor']:.1%} do gabarito; percentual a até "
        f"{meta['tolerancia_pp']} p.p.",
        "",
        "| Braço | Acerto | Custo médio por run | Custo por resposta certa | Tokens por run "
        "| Tokens por resposta certa | Turnos | Queries | MiB lidos no BigQuery | Tempo |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, a in arms.items():
        mib = None if a["bytes_bq_medio"] is None else a["bytes_bq_medio"] / 1024**2
        read = "local" if a["camada"] == "csv" else _num(mib, "{:.1f}")
        lines.append(
            f"| {key}, {a['label']} | {a['certos']}/{a['runs']} | {_usd(a['custo_medio_usd'])} "
            f"| {_usd(a['custo_por_certo_usd'])} | {_num(a['tokens_por_run'])} "
            f"| {_num(a['tokens_por_certo'])} | {_num(a['turnos_medio'], '{:.1f}')} "
            f"| {_num(a['queries_medio'], '{:.1f}')} | {read} "
            f"| {_num(a['tempo_medio_s'])} s |"
        )

    usage = meta["modelos_uso"]
    lines += ["", "## Modelos e tokens", ""]
    for model, u in sorted(usage.items(), key=lambda item: -item[1]["custo_usd"]):
        total = sum(u.get(name, 0.0) for _, name in _TOKEN_TYPES)
        lines.append(
            f"- `{model}`: chamado em {u['runs']:.0f} runs, {total:,.0f} tokens, "
            f"{_usd(u['custo_usd'])} no total."
        )
    versions = ", ".join(f"{v} ({n})" for v, n in meta["claude_code"].items())
    lines += [
        f"- Claude Code: {versions}.",
        "",
        "Tokens somados por braço, de todos os modelos:",
        "",
        "| Braço | Entrada | Escrita de cache | Leitura de cache | Saída | Total "
        "| Por run | Por resposta certa |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, a in arms.items():
        t = a["tokens"]
        lines.append(
            f"| {key} | {t['entrada']:,.0f} | {t['cache_escrita']:,.0f} "
            f"| {t['cache_leitura']:,.0f} | {t['saida']:,.0f} | {t['total']:,.0f} "
            f"| {_num(a['tokens_por_run'], '{:,.0f}')} "
            f"| {_num(a['tokens_por_certo'], '{:,.0f}')} |"
        )

    qids = list(summary["perguntas"])
    lines += ["", "## Acertos por pergunta", "", "| Braço | " + " | ".join(qids) + " |"]
    lines.append("| --- |" + " --- |" * len(qids))
    for key, a in arms.items():
        cells = [f"{a['por_pergunta'][q]['certos']}/{a['por_pergunta'][q]['runs']}" for q in qids]
        lines.append(f"| {key} | " + " | ".join(cells) + " |")

    lines += ["", "## Erros", ""]
    for key, a in arms.items():
        erros = ", ".join(f"{label} ({n})" for label, n in a["erros"].items()) or "nenhum"
        lines.append(f"- **{key}**: {erros}")
    if "B" in arms:
        b = arms["B"]
        lines.append(f"- A skill foi aberta em {b['skill_aberta']} de {b['runs']} runs do B.")

    lines += [
        "",
        "## Como cada run chegou à resposta",
        "",
        "Certo limpo: não caiu em armadilha. Certo corrigindo: caiu (na bronze, somou "
        "todas as cargas; no CSV, errou encoding, tipo ou vírgula), mas a resposta se apoia "
        "em queries corretas. Certo por sorte: bateu com o gabarito por causa de como este "
        "dado é. Na bronze, todas as somas que a resposta cita pegaram todas as cargas (a "
        "inflação se cancela numa razão, ou o período só existe numa carga). No CSV, a soma "
        "que a resposta cita junta um cadastro lido com ignore_errors, que descarta em "
        "silêncio as linhas que não consegue ler. Heurística sobre o SQL executado.",
        "",
        "| Braço | Certo limpo | Certo corrigindo | Certo por sorte | Errado |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key, a in arms.items():
        c = a["caminhos"]
        lines.append(
            f"| {key} | {c['certo_limpo']} | {c['certo_corrigindo']} "
            f"| {c['certo_por_sorte']} | {c['errado']} |"
        )
    lines += ["", "Armadilhas em que ao menos uma query caiu, por braço:", ""]
    for key, a in arms.items():
        traps = ", ".join(f"{t} ({n})" for t, n in a["tropecos"].items()) or "nenhuma"
        lines.append(f"- **{key}**: {a['runs_com_tropeco']} de {a['runs']} runs. {traps}")

    diag = summary["diagnosticos"]
    all_snapshots = diag["q1_todos_snapshots_razao"]
    no_replace = diag["q1_sem_trocar_virgula_razao"]
    lines += [
        "",
        "## Os atalhos ingênuos, na pergunta 1",
        "",
        f"- Somar todos os snapshots: {all_snapshots:.2f} vezes o valor certo.",
        f"- Converter sem trocar a vírgula: {no_replace:.2%} do valor certo.",
        "",
        "## Perguntas",
        "",
    ]
    for qid, q in summary["perguntas"].items():
        lines.append(f"- **{qid}**: {q['texto']} _Armadilha: {q['armadilha']}._")
    return "\n".join(lines) + "\n"


def write_csv(summary: dict[str, Any], path: Path) -> None:
    rows = summary["runs"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, help="diretório com runs.jsonl")
    parser.add_argument("--truth", type=Path, default=Path("evals/precisao/results/truth.json"))
    args = parser.parse_args()

    runs_path = args.results / "runs.jsonl"
    if not runs_path.exists():
        print(f"ERRO: {runs_path} não existe", file=sys.stderr)
        return 1
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    summary = summarize(load_runs(runs_path), truth)

    (args.results / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = render_markdown(summary)
    (args.results / "summary.md").write_text(markdown, encoding="utf-8")
    write_csv(summary, args.results / "summary.csv")
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
