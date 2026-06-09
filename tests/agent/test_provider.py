from src.agent.main import _provider_env
from src.config import Settings


def test_anthropic_provider_env_passes_api_key() -> None:
    settings = Settings(anthropic_api_key="sk-test")
    assert _provider_env(settings) == {"ANTHROPIC_API_KEY": "sk-test"}


def test_local_provider_env_points_to_lmstudio() -> None:
    settings = Settings(agent_provider="local", lmstudio_base_url="http://localhost:1234")
    env = _provider_env(settings)
    assert env == {
        "ANTHROPIC_BASE_URL": "http://localhost:1234",
        "ANTHROPIC_AUTH_TOKEN": "lmstudio",
    }
    # No Anthropic key leaks into the local run.
    assert "ANTHROPIC_API_KEY" not in env


def test_provider_defaults_to_anthropic() -> None:
    assert Settings().agent_provider == "anthropic"
