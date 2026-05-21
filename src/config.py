"""Central config loader.

Reads from the process environment (populated via `.env` by python-dotenv).
Pydantic does the validation so the rest of the code can rely on typed values.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseModel):
    env: str = Field(default="dev")
    aws_s3_bucket: str = Field(default="susep-ses-data")
    aws_region: str = Field(default="us-east-1")
    gcp_project_id: str = Field(default="")
    gcp_bq_dataset_bronze: str = Field(default="susep_ses_bronze")
    gcp_bq_dataset_staging: str = Field(default="susep_ses_staging")
    gcp_bq_dataset_marts: str = Field(default="susep_ses_marts")
    susep_ses_url: str = Field(
        default="https://www2.susep.gov.br/menuestatistica/SES/principal.aspx"
    )

    # Insights agent (CP-C). The API key is read but never logged.
    anthropic_api_key: str = Field(default="")
    agent_model: str = Field(default="sonnet")
    agent_max_turns: int = Field(default=20)
    agent_max_budget_usd: float = Field(default=0.50)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance. `.env` is loaded on first access."""
    if _ENV_FILE.exists():
        # Some runners inject env vars as empty strings (e.g. ANTHROPIC_API_KEY="").
        # An empty inherited var must NOT shadow a real value in .env, so treat
        # empty as unset before loading. Non-empty env vars are preserved and
        # still win (override=False) — important for CI, where there's no .env
        # and the real secrets come from the environment.
        for key in dotenv_values(_ENV_FILE):
            if os.environ.get(key) == "":
                del os.environ[key]
        load_dotenv(_ENV_FILE, override=False)

    return Settings(
        env=os.getenv("ENV", "dev"),
        aws_s3_bucket=os.getenv("AWS_S3_BUCKET", "susep-ses-data"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        gcp_project_id=os.getenv("GCP_PROJECT_ID", ""),
        gcp_bq_dataset_bronze=os.getenv("GCP_BQ_DATASET_BRONZE", "susep_ses_bronze"),
        gcp_bq_dataset_staging=os.getenv("GCP_BQ_DATASET_STAGING", "susep_ses_staging"),
        gcp_bq_dataset_marts=os.getenv("GCP_BQ_DATASET_MARTS", "susep_ses_marts"),
        susep_ses_url=os.getenv(
            "SUSEP_SES_URL",
            "https://www2.susep.gov.br/menuestatistica/SES/principal.aspx",
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        agent_model=os.getenv("AGENT_MODEL", "sonnet"),
        agent_max_turns=int(os.getenv("AGENT_MAX_TURNS", "20")),
        agent_max_budget_usd=float(os.getenv("AGENT_MAX_BUDGET_USD", "0.50")),
    )
