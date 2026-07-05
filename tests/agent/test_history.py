import pytest

from src.agent.history import build_history_digest, next_mode, read_report
from tests.agent._fakes import FakeStore


def test_next_mode_alternates_deterministically() -> None:
    # Empty history → first report is a broad baseline (novo ângulo).
    assert next_mode({"reports": []}) == "novo ângulo"
    # Last report was novo ângulo → flip to deep-dive, and vice-versa.
    assert next_mode({"reports": [{"stem": "2026-07-05", "mode": "novo ângulo"}]}) == "deep-dive"
    assert next_mode({"reports": [{"stem": "2026-07-05", "mode": "deep-dive"}]}) == "novo ângulo"
    # Old entries without a recorded mode bootstrap into a deep-dive.
    assert next_mode({"reports": [{"stem": "2026-07-05"}]}) == "deep-dive"
    # The LATEST stem decides — same-day reruns sort after the base stem.
    manifest = {
        "reports": [
            {"stem": "2026-07-05_2", "mode": "deep-dive"},
            {"stem": "2026-07-05", "mode": "novo ângulo"},
        ]
    }
    assert next_mode(manifest) == "novo ângulo"


def _seed(store: FakeStore) -> None:
    store.save_manifest(
        {
            "reports": [
                {
                    "stem": "2026-05-20",
                    "report_path": "reports/2026/2026-05-20.md",
                    "queries_path": None,
                    "titles": ["1. Auto loss ratio elevado", "2. Saúde melhora"],
                },
                {
                    "stem": "2026-05-21",
                    "report_path": "reports/2026/2026-05-21.md",
                    "queries_path": "queries/2026/2026-05-21.sql.md",
                    "titles": ["1. Concentração de mercado"],
                },
            ]
        }
    )
    store.objects["reports/2026/2026-05-20.md"] = "# Report antigo\nSQL inline aqui\n"
    store.objects["reports/2026/2026-05-21.md"] = "# Report novo\nsó análise\n"
    store.objects["queries/2026/2026-05-21.sql.md"] = "## Query 1\nSELECT 1"


def test_digest_fallback_when_empty() -> None:
    out = build_history_digest(store=FakeStore())
    assert "primeiro" in out.lower()


def test_digest_lists_dates_and_titles_recent_first() -> None:
    store = FakeStore()
    _seed(store)
    out = build_history_digest(store=store)
    assert out.index("2026-05-21") < out.index("2026-05-20")
    assert "- 1. Auto loss ratio elevado" in out
    assert "- 2. Saúde melhora" in out
    assert "- 1. Concentração de mercado" in out


def test_digest_includes_same_day_reruns() -> None:
    store = FakeStore()
    _seed(store)
    manifest = store.load_manifest()
    manifest["reports"].append(
        {
            "stem": "2026-05-21_2",
            "report_path": "reports/2026/2026-05-21_2.md",
            "queries_path": None,
            "titles": ["1. Deep-dive na concentração"],
        }
    )
    store.save_manifest(manifest)

    out = build_history_digest(store=store)
    assert "2026-05-21_2" in out
    assert "- 1. Deep-dive na concentração" in out


def test_digest_respects_max_reports() -> None:
    store = FakeStore()
    _seed(store)
    out = build_history_digest(store=store, max_reports=1)
    assert "2026-05-21" in out
    assert "2026-05-20" not in out


def test_read_report_returns_full_text() -> None:
    store = FakeStore()
    _seed(store)
    out = read_report("2026-05-20", store=store)
    assert out == "# Report antigo\nSQL inline aqui\n"


def test_read_report_appends_queries_appendix_when_present() -> None:
    store = FakeStore()
    _seed(store)
    out = read_report("2026-05-21", store=store)
    assert out.startswith("# Report novo")
    assert "## Query 1\nSELECT 1" in out


def test_read_report_validates_date_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        read_report("20-05-2026", store=FakeStore())


def test_read_report_missing_report() -> None:
    with pytest.raises(FileNotFoundError):
        read_report("2026-01-01", store=FakeStore())
