import pytest

from sungrid_copilot.config import ConfigError, LLMSettings, RoleSettings, Settings, load_settings
from sungrid_copilot.llm.anthropic_client import AnthropicClient
from sungrid_copilot.llm.azure_openai import AzureOpenAIClient
from sungrid_copilot.llm.factory import describe_provider, get_llm_client
from sungrid_copilot.llm.fake import FakeLLMClient
from sungrid_copilot.llm.gemini_client import GeminiClient
from sungrid_copilot.llm.openai_client import OpenAIClient

PROVIDER_ENV = {
    "azure_openai": {
        "AZURE_OPENAI_API_KEY": "fake-key",
        "AZURE_OPENAI_ENDPOINT": "https://example-resource.openai.azure.com/",
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
    },
    "openai": {"OPENAI_API_KEY": "fake-key", "OPENAI_MODEL": "some-model"},
    "anthropic": {"ANTHROPIC_API_KEY": "fake-key", "ANTHROPIC_MODEL": "some-model"},
    "gemini": {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": "some-model"},
    "fake": {},
}
EXPECTED_CLASS = {
    "azure_openai": AzureOpenAIClient,
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
    "gemini": GeminiClient,
    "fake": FakeLLMClient,
}


@pytest.mark.parametrize("provider", list(EXPECTED_CLASS))
def test_factory_selects_client_from_llm_provider(monkeypatch, provider):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    for name, value in PROVIDER_ENV[provider].items():
        monkeypatch.setenv(name, value)
    client = get_llm_client()
    assert type(client) is EXPECTED_CLASS[provider]
    assert client.provider == provider


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_factory_missing_variable_is_named(monkeypatch, provider):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    env = PROVIDER_ENV[provider]
    key_var = next(name for name in env if name.endswith("API_KEY"))
    for name, value in env.items():
        if name != key_var:
            monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=key_var):
        get_llm_client()


def test_env_provider_overrides_yaml(monkeypatch):
    assert load_settings().llm.provider == "azure_openai"  # config.yaml default
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert load_settings().llm.provider == "fake"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        load_settings()


def test_role_override_and_default(monkeypatch):
    for name, value in PROVIDER_ENV["azure_openai"].items():
        monkeypatch.setenv(name, value)
    settings = Settings(
        llm=LLMSettings(provider="azure_openai", roles={"classifier": RoleSettings(model="gpt-4o-mini")})
    )
    assert get_llm_client("classifier", settings).model == "gpt-4o-mini"
    assert get_llm_client("answerer", settings).model == "gpt-4o"
    assert get_llm_client(settings=settings).model == "gpt-4o"


def test_unknown_role_is_rejected():
    with pytest.raises(ConfigError, match="role"):
        get_llm_client("summariser", Settings(llm=LLMSettings(provider="fake")))


def test_describe_provider_never_shows_key_or_full_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "very-secret-value-123")
    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "https://example-resource.openai.azure.com/openai/deployments/gpt-4o/chat/completions"
        "?api-version=2025-01-01-preview",
    )
    info = describe_provider(load_settings())
    assert info["API key"] == "set"
    assert info["Endpoint host"] == "example-resource.openai.azure.com"
    assert info["Deployment"] == "(not set)"
    assert "very-secret-value-123" not in str(info)
    assert "/openai/deployments" not in str(info)


def test_describe_provider_reports_missing_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    assert describe_provider(load_settings())["API key"] == "MISSING"
