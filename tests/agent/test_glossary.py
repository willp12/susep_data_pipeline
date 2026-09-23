import json
from pathlib import Path

from src.agent.glossary import build_glossary


def test_build_glossary_returns_fallback_when_manifest_missing(tmp_path: Path) -> None:
    result = build_glossary(manifest_path=tmp_path / "nope.json")
    assert "describe_table" in result
    assert "unavailable" in result.lower()


def test_build_glossary_flattens_sources_and_models(tmp_path: Path) -> None:
    manifest = {
        "sources": {
            "source.p.susep_ses_bronze.ses_seguros": {
                "schema": "susep_ses_bronze",
                "name": "ses_seguros",
                "description": "raw bronze",
                "columns": {
                    "coenti": {"description": "insurer code"},
                    "_extras": {"description": ""},
                },
            }
        },
        "nodes": {
            "model.p.stg_ses_seguros": {
                "resource_type": "model",
                "schema": "susep_ses_staging",
                "name": "stg_ses_seguros",
                "description": "typed view",
                "columns": {"periodo_ref": {"description": "competence month"}},
            },
            "test.p.some_test": {"resource_type": "test"},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = build_glossary(manifest_path=path)

    assert "susep_ses_bronze.ses_seguros" in result
    assert "insurer code" in result
    assert "susep_ses_staging.stg_ses_seguros" in result
    assert "competence month" in result
    # Column with no description still appears, just without text.
    assert "`_extras`" in result
    # Non-model nodes (tests) are skipped.
    assert "some_test" not in result


def test_build_glossary_keeps_only_the_requested_schemas(tmp_path: Path) -> None:
    manifest = {
        "sources": {
            "source.p.susep_ses_bronze.ses_seguros": {
                "schema": "susep_ses_bronze",
                "name": "ses_seguros",
                "description": "raw bronze",
                "columns": {"coenti": {"description": "insurer code"}},
            }
        },
        "nodes": {
            "model.p.stg_ses_seguros": {
                "resource_type": "model",
                "schema": "susep_ses_staging",
                "name": "stg_ses_seguros",
                "description": "typed view",
                "columns": {},
            },
            "model.p.fct_seguros": {
                "resource_type": "model",
                "schema": "susep_ses_marts",
                "name": "fct_seguros",
                "description": "curated fact",
                "columns": {"premio_direto": {"description": "direct premium"}},
            },
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = build_glossary(manifest_path=path, schemas={"susep_ses_marts"})

    assert "susep_ses_marts.fct_seguros" in result
    assert "direct premium" in result
    assert "susep_ses_bronze" not in result
    assert "susep_ses_staging" not in result
