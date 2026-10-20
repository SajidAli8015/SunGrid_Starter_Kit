"""Azure OpenAI chat client (the only provider tested end to end)."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, SecretStr

from sungrid_copilot.config import ConfigError, LLMSettings, require_env
from sungrid_copilot.llm.base import (
    LLMClient,
    LLMContentFilterError,
    LLMError,
    LLMResponse,
    Message,
)

PROVIDER = "azure_openai"
DEFAULT_API_VERSION = "2024-02-01"


def normalise_endpoint(endpoint: str) -> str:
    """Reduce a full request URL to the resource root `scheme://host/` that the SDK expects."""
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise ConfigError(
            "AZURE_OPENAI_ENDPOINT must be a URL like https://<your-resource>.openai.azure.com/"
        )
    return f"{parts.scheme}://{parts.netloc}/"


def resolve_api_version(env_value: str | None, endpoint: str) -> str:
    """AZURE_OPENAI_API_VERSION, else `api-version` in the endpoint query, else the default."""
    if env_value and env_value.strip():
        return env_value.strip()
    from_query = parse_qs(urlsplit(endpoint.strip()).query).get("api-version")
    if from_query and from_query[0].strip():
        return from_query[0].strip()
    return DEFAULT_API_VERSION


class AzureOpenAISettings(BaseModel):
    api_key: SecretStr
    endpoint: str
    deployment: str
    api_version: str

    @classmethod
    def from_env(cls) -> AzureOpenAISettings:
        raw_endpoint = require_env("AZURE_OPENAI_ENDPOINT", PROVIDER)
        return cls(
            api_key=SecretStr(require_env("AZURE_OPENAI_API_KEY", PROVIDER)),
            endpoint=normalise_endpoint(raw_endpoint),
            deployment=require_env("AZURE_OPENAI_DEPLOYMENT", PROVIDER),
            api_version=resolve_api_version(os.environ.get("AZURE_OPENAI_API_VERSION"), raw_endpoint),
        )


def is_input_content_filter(e: Exception) -> bool:
    """Azure rejects a filtered prompt with HTTP 400 and error code `content_filter`.
    Duck-typed so it can be tested without the SDK's exception classes."""
    return getattr(e, "status_code", None) == 400 and getattr(e, "code", None) == "content_filter"


def describe_env() -> dict[str, str]:
    """What `check-llm` prints before connecting. Never includes the key or the full URL."""
    raw_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    try:
        host = urlsplit(normalise_endpoint(raw_endpoint)).hostname or "(invalid)"
    except ConfigError:
        host = "(not set)" if not raw_endpoint else "(invalid)"
    return {
        "Deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip() or "(not set)",
        "Endpoint host": host,
        "API version": resolve_api_version(os.environ.get("AZURE_OPENAI_API_VERSION"), raw_endpoint),
        "API key": "set" if os.environ.get("AZURE_OPENAI_API_KEY", "").strip() else "MISSING",
    }


class AzureOpenAIClient(LLMClient):
    provider = PROVIDER

    def __init__(self, llm: LLMSettings, *, model_override: str | None = None):
        settings = AzureOpenAISettings.from_env()
        api_key = settings.api_key.get_secret_value()
        super().__init__(
            model=model_override or settings.deployment,
            temperature=llm.temperature,
            secrets=(api_key,),
        )
        try:
            from openai import AzureOpenAI
        except ImportError as e:
            raise LLMError("The 'openai' package is required for azure_openai.") from e
        self.endpoint = settings.endpoint
        self.api_version = settings.api_version
        self._client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=settings.endpoint,
            api_version=settings.api_version,
            timeout=llm.timeout_s,
            max_retries=llm.max_retries,
        )

    def _translate_error(self, e: Exception) -> LLMError | None:
        if is_input_content_filter(e):
            return LLMContentFilterError("azure_openai rejected the input (content filter).")
        return None

    def _complete(
        self, system: str, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> LLMResponse:
        # `model` is the deployment name on Azure.
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model or self.model,
        )
