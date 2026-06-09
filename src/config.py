"""Central config loader.

Reads from the process environment (populated via `.env` by python-dotenv).
Pydantic does the validation so the rest of the code can rely on typed values.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    # Empty when GCP_PROJECT_ID is also empty; derived in get_settings otherwise.
    gcp_reports_bucket: str = Field(default="")
    susep_ses_url: str = Field(
        default="https://www2.susep.gov.br/menuestatistica/SES/principal.aspx"
    )

    # Insights agent (CP-C). The API key is read but never logged.
    anthropic_api_key: str = Field(default="")
    agent_model: str = Field(default="sonnet")
    agent_max_turns: int = Field(default=20)
    agent_max_budget_usd: float = Field(default=0.75)

    # 'local' points the Agent SDK at LM Studio's Anthropic-compatible
    # /v1/messages endpoint instead of the Anthropic API (no key needed).
    agent_provider: Literal["anthropic", "local"] = Field(default="anthropic")
    lmstudio_base_url: str = Field(default="http://localhost:1234")

    # Report e-mail delivery (optional — leaving these empty disables sending).
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=465)
    smtp_username: str = Field(default="")
    smtp_app_password: str = Field(default="")
    report_email_to: str = Field(default="")
    report_email_from: str = Field(default="")


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

    project_id = os.getenv("GCP_PROJECT_ID", "")
    default_reports_bucket = f"{project_id}-susep-ses-reports" if project_id else ""

    return Settings(
        env=os.getenv("ENV", "dev"),
        aws_s3_bucket=os.getenv("AWS_S3_BUCKET", "susep-ses-data"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        gcp_project_id=os.getenv("GCP_PROJECT_ID", ""),
        gcp_bq_dataset_bronze=os.getenv("GCP_BQ_DATASET_BRONZE", "susep_ses_bronze"),
        gcp_bq_dataset_staging=os.getenv("GCP_BQ_DATASET_STAGING", "susep_ses_staging"),
        gcp_bq_dataset_marts=os.getenv("GCP_BQ_DATASET_MARTS", "susep_ses_marts"),
        gcp_reports_bucket=os.getenv("GCP_REPORTS_BUCKET") or default_reports_bucket,
        susep_ses_url=os.getenv(
            "SUSEP_SES_URL",
            "https://www2.susep.gov.br/menuestatistica/SES/principal.aspx",
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        agent_model=os.getenv("AGENT_MODEL", "sonnet"),
        agent_max_turns=int(os.getenv("AGENT_MAX_TURNS", "20")),
        agent_max_budget_usd=float(os.getenv("AGENT_MAX_BUDGET_USD", "0.75")),
        agent_provider=os.getenv("AGENT_PROVIDER", "anthropic"),  # type: ignore[arg-type]
        lmstudio_base_url=os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234"),
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_username=os.getenv("SMTP_USERNAME", ""),
        smtp_app_password=os.getenv("SMTP_APP_PASSWORD", ""),
        report_email_to=os.getenv("REPORT_EMAIL_TO", ""),
        report_email_from=os.getenv("REPORT_EMAIL_FROM", ""),
    )
