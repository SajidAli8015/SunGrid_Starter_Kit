"""Provider-independent LLM interface.

Providers implement `_complete`. The base class handles timing, wraps any provider exception
in `LLMError` (with secrets redacted), and implements `complete_json` without relying on
provider-specific structured-output features.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

Message = dict[str, str]  # {"role": "user" | "assistant", "content": "..."}
T = TypeVar("T", bound=BaseModel)

_ALLOWED_ROLES = {"user", "assistant"}
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)
_MAX_ERROR_CHARS = 500


class LLMError(Exception):
    """Any failure talking to, or parsing output from, an LLM. Never contains keys or headers."""


class LLMContentFilterError(LLMError):
    """The provider rejected the INPUT with a content-filter response. Callers should treat the
    request as refused (not retried, not answered from guesswork)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_s: float = 0.0


@dataclass(frozen=True)
class JSONResponse(Generic[T]):
    """A validated object plus the raw responses it took to get it (for token/latency logging)."""

    value: T
    responses: list[LLMResponse]

    @property
    def input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.responses)

    @property
    def output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.responses)

    @property
    def latency_s(self) -> float:
        return sum(r.latency_s for r in self.responses)


class LLMClient(ABC):
    provider: str = "base"

    def __init__(self, *, model: str, temperature: float = 0.0, secrets: tuple[str, ...] = ()):
        self.model = model
        self.default_temperature = temperature
        self._secrets = tuple(s for s in secrets if s)

    @abstractmethod
    def _complete(
        self, system: str, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> LLMResponse:
        """Make one provider call. `latency_s` is filled in by `complete`."""

    def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Send a system prompt plus user/assistant messages and return the reply.

        `temperature=None` uses the configured default (`llm.temperature`).
        """
        _validate_messages(messages)
        temp = self.default_temperature if temperature is None else temperature
        start = time.perf_counter()
        try:
            response = self._complete(system, messages, temperature=temp, max_tokens=max_tokens)
        except LLMError:
            raise
        except Exception as e:  # any SDK failure (auth, HTTP, timeout) becomes one typed error
            translated = self._translate_error(e)
            if translated is not None:
                raise translated from e
            raise LLMError(f"{self.provider} request failed: {self._safe_error(e)}") from e
        return replace(response, latency_s=time.perf_counter() - start)

    def complete_json(
        self,
        system: str,
        messages: list[Message],
        schema: type[T],
        *,
        retries: int = 1,
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> JSONResponse[T]:
        """Ask for JSON only, validate it against `schema`, retry with the validation error.

        Raises LLMError if the reply is still invalid after `retries` extra attempts.
        """
        json_system = (
            f"{system}\n\n"
            "Respond with a single JSON object only: no prose, no code fences. "
            "It must validate against this JSON schema:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        conversation = list(messages)
        responses: list[LLMResponse] = []
        last_error = ""
        for _ in range(retries + 1):
            response = self.complete(
                json_system, conversation, temperature=temperature, max_tokens=max_tokens
            )
            responses.append(response)
            try:
                value = schema.model_validate_json(strip_code_fences(response.text))
                return JSONResponse(value=value, responses=responses)
            except ValidationError as e:
                last_error = str(e)[:_MAX_ERROR_CHARS]
                conversation += [
                    {"role": "assistant", "content": response.text},
                    {
                        "role": "user",
                        "content": "Your previous reply was not valid JSON for the schema:\n"
                        f"{last_error}\nReply again with only the corrected JSON object.",
                    },
                ]
        raise LLMError(
            f"{self.provider} returned invalid JSON for {schema.__name__} after "
            f"{retries + 1} attempt(s): {last_error}"
        )

    def _translate_error(self, e: Exception) -> LLMError | None:
        """Providers override this to map specific SDK errors to typed LLMError subclasses."""
        return None

    def _safe_error(self, e: Exception) -> str:
        message = f"{type(e).__name__}: {e}"
        for secret in self._secrets:
            message = message.replace(secret, "***")
        return message[:_MAX_ERROR_CHARS]


def strip_code_fences(text: str) -> str:
    """Remove a surrounding ```json ... ``` fence if present."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text.strip()


def _validate_messages(messages: list[Message]) -> None:
    if not messages:
        raise LLMError("At least one message is required.")
    for m in messages:
        if m.get("role") not in _ALLOWED_ROLES or not isinstance(m.get("content"), str):
            raise LLMError("Messages must be {'role': 'user'|'assistant', 'content': str}.")
