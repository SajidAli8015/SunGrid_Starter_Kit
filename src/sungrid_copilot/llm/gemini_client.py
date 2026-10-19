"""Google Gemini client (google-genai SDK). Not tested end to end (see NOTES.md)."""

from __future__ import annotations

import os

from pydantic import BaseModel, SecretStr

from sungrid_copilot.config import LLMSettings, require_env
from sungrid_copilot.llm.base import LLMClient, LLMError, LLMResponse, Message

PROVIDER = "gemini"


class GeminiSettings(BaseModel):
    api_key: SecretStr
    model: str

    @classmethod
    def from_env(cls) -> GeminiSettings:
        return cls(
            api_key=SecretStr(require_env("GEMINI_API_KEY", PROVIDER)),
            model=require_env("GEMINI_MODEL", PROVIDER),
        )


def describe_env() -> dict[str, str]:
    return {
        "Model": os.environ.get("GEMINI_MODEL", "").strip() or "(not set)",
        "API key": "set" if os.environ.get("GEMINI_API_KEY", "").strip() else "MISSING",
    }


class GeminiClient(LLMClient):
    provider = PROVIDER

    def __init__(self, llm: LLMSettings, *, model_override: str | None = None):
        settings = GeminiSettings.from_env()
        api_key = settings.api_key.get_secret_value()
        super().__init__(
            model=model_override or settings.model, temperature=llm.temperature, secrets=(api_key,)
        )
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LLMError("The 'google-genai' package is required for gemini.") from e
        self._types = types
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(llm.timeout_s * 1000),  # milliseconds
                retry_options=types.HttpRetryOptions(attempts=llm.max_retries + 1),
            ),
        )

    def _complete(
        self, system: str, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> LLMResponse:
        types = self._types
        # Gemini calls the assistant role "model".
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]
        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        usage = response.usage_metadata
        return LLMResponse(
            text=response.text or "",
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            model=self.model,
        )
