from datetime import date
from pathlib import Path

import pytest

from src.agent.history import build_history_digest, read_report

_REPORT_A = """---
date: 2026-05-20
---
# Insights SUSEP SES — 2026-05-20
## Insights
### 1. Auto loss ratio elevado
texto
### 2. Saúde melhora
texto
"""

_REPORT_B = """---
date: 2026-05-21
---
### 1. Concentração de mercado
texto
"""


def _seed(tmp_path: Path) -> Path:
    (tmp_path / "2026-05-20.md").write_text(_REPORT_A, encoding="utf-8")
    (tmp_path / "2026-05-21.md").write_text(_REPORT_B, encoding="utf-8")
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    return tmp_path


def test_digest_fallback_when_empty(tmp_path: Path) -> None:
    out = build_history_digest(reports_dir=tmp_path)
    assert "primeiro" in out.lower()


def test_digest_lists_dates_and_titles_recent_first(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = build_history_digest(reports_dir=tmp_path)
    # Most recent date appears before the older one.
    assert out.index("2026-05-21") < out.index("2026-05-20")
    assert "- 1. Auto loss ratio elevado" in out
    assert "- 2. Saúde melhora" in out
    assert "- 1. Concentração de mercado" in out


def test_digest_excludes_given_date(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = build_history_digest(reports_dir=tmp_path, exclude=date(2026, 5, 21))
    assert "2026-05-21" not in out
    assert "2026-05-20" in out


def test_digest_respects_max_reports(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = build_history_digest(reports_dir=tmp_path, max_reports=1)
    # Only the most recent report is included.
    assert "2026-05-21" in out
    assert "2026-05-20" not in out


def test_read_report_returns_full_text(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert read_report("2026-05-20", reports_dir=tmp_path) == _REPORT_A


def test_read_report_validates_date_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        read_report("20-05-2026", reports_dir=tmp_path)


def test_read_report_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_report("2026-01-01", reports_dir=tmp_path)
