import pytest

from sungrid_copilot.config import ConfigError
from sungrid_copilot.llm.azure_openai import (
    DEFAULT_API_VERSION,
    AzureOpenAISettings,
    normalise_endpoint,
    resolve_api_version,
)

FULL_URL = (
    "https://example-resource.openai.azure.com/openai/deployments/gpt-4o/chat/completions"
    "?api-version=2025-01-01-preview"
)
ROOT = "https://example-resource.openai.azure.com/"


@pytest.mark.parametrize(
    "endpoint",
    [FULL_URL, ROOT, "https://example-resource.openai.azure.com", f"  {FULL_URL}  "],
)
def test_endpoint_is_normalised_to_resource_root(endpoint):
    assert normalise_endpoint(endpoint) == ROOT


@pytest.mark.parametrize("endpoint", ["", "example-resource.openai.azure.com", "ftp://x/"])
def test_invalid_endpoint_names_the_variable(endpoint):
    with pytest.raises(ConfigError, match="AZURE_OPENAI_ENDPOINT"):
        normalise_endpoint(endpoint)


def test_api_version_env_var_wins():
    assert resolve_api_version("2024-06-01", FULL_URL) == "2024-06-01"


def test_api_version_from_endpoint_query():
    assert resolve_api_version(None, FULL_URL) == "2025-01-01-preview"
    assert resolve_api_version("  ", FULL_URL) == "2025-01-01-preview"


def test_api_version_default():
    assert resolve_api_version(None, ROOT) == DEFAULT_API_VERSION == "2024-02-01"


def _set_azure_env(monkeypatch, **overrides):
    values = {
        "AZURE_OPENAI_API_KEY": "fake-key",
        "AZURE_OPENAI_ENDPOINT": FULL_URL,
        "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_settings_from_env(monkeypatch):
    _set_azure_env(monkeypatch)
    settings = AzureOpenAISettings.from_env()
    assert settings.endpoint == ROOT
    assert settings.deployment == "gpt-4o"
    assert settings.api_version == "2025-01-01-preview"


@pytest.mark.parametrize(
    "missing", ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"]
)
def test_missing_variable_is_named(monkeypatch, missing):
    _set_azure_env(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(ConfigError) as excinfo:
        AzureOpenAISettings.from_env()
    assert missing in str(excinfo.value)
    assert "azure_openai" in str(excinfo.value)


def test_secret_is_masked_in_repr_and_str(monkeypatch):
    secret = "very-secret-value-123"
    _set_azure_env(monkeypatch, AZURE_OPENAI_API_KEY=secret)
    settings = AzureOpenAISettings.from_env()
    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in str(settings.model_dump())
    assert settings.api_key.get_secret_value() == secret
