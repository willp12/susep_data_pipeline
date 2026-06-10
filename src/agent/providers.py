"""Provider selection for SDK-spawned agent processes.

Shared by the daily insights agent (src.agent.main) and the interactive chat
(src.chat): both run the same Claude Agent SDK against either the Anthropic
API or LM Studio's Anthropic-compatible endpoint.
"""

from __future__ import annotations

from src.config import Settings


def provider_env(settings: Settings) -> dict[str, str]:
    """Env for the SDK-spawned CLI process, per provider.

    'local' targets LM Studio's Anthropic-compatible /v1/messages endpoint
    (LM Studio >= 0.4.1): same SDK, different base URL, dummy token. Set
    AGENT_MODEL to the LM Studio model id (e.g. qwen/qwen3-14b).
    """
    if settings.agent_provider == "local":
        return {
            "ANTHROPIC_BASE_URL": settings.lmstudio_base_url,
            "ANTHROPIC_AUTH_TOKEN": "lmstudio",
        }
    return {"ANTHROPIC_API_KEY": settings.anthropic_api_key}


def require_provider_credentials(settings: Settings) -> None:
    """Fail fast when the chosen provider can't authenticate."""
    if settings.agent_provider == "anthropic" and not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — populate .env (see .env.example).")
