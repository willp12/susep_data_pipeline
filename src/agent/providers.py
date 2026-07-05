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

    For the anthropic provider, a CLAUDE_CODE_OAUTH_TOKEN (from
    `claude setup-token`, Pro/Max plans) wins over the API key: setting it is
    an explicit opt-in to bill runs against the Claude subscription instead
    of API credits. Only one credential is ever passed to the CLI.
    """
    if settings.agent_provider == "local":
        return {
            "ANTHROPIC_BASE_URL": settings.lmstudio_base_url,
            "ANTHROPIC_AUTH_TOKEN": "lmstudio",
        }
    if settings.claude_code_oauth_token:
        return {"CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token}
    return {"ANTHROPIC_API_KEY": settings.anthropic_api_key}


def require_provider_credentials(settings: Settings) -> None:
    """Fail fast when the chosen provider can't authenticate."""
    if settings.agent_provider == "anthropic" and not (
        settings.anthropic_api_key or settings.claude_code_oauth_token
    ):
        raise RuntimeError(
            "Neither ANTHROPIC_API_KEY nor CLAUDE_CODE_OAUTH_TOKEN set — "
            "populate .env (see .env.example)."
        )
