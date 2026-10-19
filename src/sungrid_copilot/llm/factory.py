"""Pick the LLM client from settings. Provider modules are imported only when selected."""

from __future__ import annotations

import importlib
from typing import get_args

from sungrid_copilot.config import ConfigError, Role, Settings, load_settings
from sungrid_copilot.llm.base import LLMClient

# provider -> (module, client class)
_PROVIDERS = {
    "azure_openai": ("sungrid_copilot.llm.azure_openai", "AzureOpenAIClient"),
    "openai": ("sungrid_copilot.llm.openai_client", "OpenAIClient"),
    "anthropic": ("sungrid_copilot.llm.anthropic_client", "AnthropicClient"),
    "gemini": ("sungrid_copilot.llm.gemini_client", "GeminiClient"),
    "fake": ("sungrid_copilot.llm.fake", "FakeLLMClient"),
}

# Lets `check-llm` (plain reply and its tiny JSON schema) run offline. Tests script their own.
FAKE_DEFAULT_RESPONSE = '{"status": "ok"}'


def _module(provider: str):
    if provider not in _PROVIDERS:
        raise ConfigError(f"Unknown LLM provider '{provider}'. Choose one of: {', '.join(_PROVIDERS)}.")
    return importlib.import_module(_PROVIDERS[provider][0])


def get_llm_client(role: Role = "default", settings: Settings | None = None) -> LLMClient:
    """Build the client for `LLM_PROVIDER` (or `llm.provider`), with the role's model override."""
    if role not in get_args(Role):
        raise ConfigError(f"Unknown LLM role '{role}'. Choose one of: {', '.join(get_args(Role))}.")
    settings = settings or load_settings()
    provider = settings.llm.provider
    client_cls = getattr(_module(provider), _PROVIDERS[provider][1])
    model_override = settings.llm.model_for_role(role)

    if provider == "fake":
        return client_cls(
            default=FAKE_DEFAULT_RESPONSE,
            model=model_override or "fake",
            temperature=settings.llm.temperature,
        )
    return client_cls(settings.llm, model_override=model_override)


def describe_provider(settings: Settings) -> dict[str, str]:
    """Non-secret summary of the selected provider's environment, without connecting."""
    return {"Provider": settings.llm.provider, **_module(settings.llm.provider).describe_env()}
