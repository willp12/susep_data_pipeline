import pytest

from src.agent.providers import provider_env, require_provider_credentials
from src.config import Settings


def test_anthropic_provider_env_passes_api_key() -> None:
    settings = Settings(anthropic_api_key="sk-test")
    assert provider_env(settings) == {"ANTHROPIC_API_KEY": "sk-test"}


def test_oauth_token_wins_over_api_key() -> None:
    settings = Settings(anthropic_api_key="sk-test", claude_code_oauth_token="sk-ant-oat01-x")
    env = provider_env(settings)
    assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-x"}
    # Exactly one credential reaches the spawned CLI.
    assert "ANTHROPIC_API_KEY" not in env


def test_oauth_token_alone_is_enough() -> None:
    settings = Settings(claude_code_oauth_token="sk-ant-oat01-x")
    assert provider_env(settings) == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-x"}


def test_local_provider_env_points_to_lmstudio() -> None:
    settings = Settings(agent_provider="local", lmstudio_base_url="http://localhost:1234")
    env = provider_env(settings)
    assert env == {
        "ANTHROPIC_BASE_URL": "http://localhost:1234",
        "ANTHROPIC_AUTH_TOKEN": "lmstudio",
    }
    # No Anthropic key leaks into the local run.
    assert "ANTHROPIC_API_KEY" not in env


def test_provider_defaults_to_anthropic() -> None:
    assert Settings().agent_provider == "anthropic"


def test_require_credentials_fails_without_key() -> None:
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        require_provider_credentials(Settings(anthropic_api_key=""))


def test_require_credentials_accepts_oauth_token() -> None:
    require_provider_credentials(Settings(claude_code_oauth_token="sk-ant-oat01-x"))


def test_require_credentials_local_needs_no_key() -> None:
    require_provider_credentials(Settings(agent_provider="local"))
