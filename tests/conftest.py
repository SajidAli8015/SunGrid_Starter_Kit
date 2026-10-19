import pytest

from sungrid_copilot import config

PROVIDER_ENV_VARS = [
    "LLM_PROVIDER",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Tests never see the developer's real .env or shell credentials."""
    monkeypatch.setattr(config, "load_env_file", lambda *args, **kwargs: None)
    for name in PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
