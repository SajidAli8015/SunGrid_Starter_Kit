"""Per-request LLM usage: every call's role, model, tokens and latency, plus estimated cost.

`TrackedLLM` wraps any `LLMClient` (provider-independent). One `UsageTracker` is shared by the
agent's clients and reset at the start of each request. Not thread-safe: one request at a time.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from sungrid_copilot.config import ModelPrice
from sungrid_copilot.llm import LLMClient, LLMError, LLMResponse
from sungrid_copilot.llm.base import Message


@dataclass(frozen=True)
class CallRecord:
    role: str
    model: str  # the configured model/deployment
    input_tokens: int
    output_tokens: int
    latency_s: float
    error: str | None = None  # exception type name if the call failed
    api_model: str | None = None  # the model the provider says it ran, e.g. gpt-4o-2024-11-20


@dataclass
class UsageTracker:
    calls: list[CallRecord] = field(default_factory=list)

    def reset(self) -> None:
        self.calls = []

    def record(self, call: CallRecord) -> None:
        self.calls.append(call)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    def by_call(self) -> list[dict]:
        return [asdict(c) | {"latency_s": round(c.latency_s, 3)} for c in self.calls]


Pricing = dict[str, dict[str, ModelPrice]]
ModelMap = dict[str, dict[str, str]]


def find_price(
    provider: str,
    model: str,
    api_model: str | None,
    pricing: Pricing,
    model_map: ModelMap | None = None,
) -> ModelPrice | None:
    """The complete price for a call, or None.

    Tried in order: the optional `pricing_model_map` entry for the configured name, the configured
    name itself, then the model the provider reported, exactly or as `<key>-YYYY-MM-DD`. The dated
    form never lets "gpt-4o-mini-2024-07-18" take the price of "gpt-4o".
    """
    table = pricing.get(provider, {})
    keys = [(model_map or {}).get(provider, {}).get(model), model, api_model]
    if api_model:
        keys += [k for k in table if re.fullmatch(rf"{re.escape(k)}-\d{{4}}-\d{{2}}-\d{{2}}", api_model)]
    for key in keys:
        price = table.get(key) if key else None
        if price is not None and price.input_per_1m is not None and price.output_per_1m is not None:
            return price
    return None


def estimate_cost(
    calls: list[CallRecord], provider: str, pricing: Pricing, model_map: ModelMap | None = None
) -> float | None:
    """USD, or None if any call's model has no complete price."""
    total = 0.0
    for c in calls:
        price = find_price(provider, c.model, c.api_model, pricing, model_map)
        if price is None:
            return None
        total += c.input_tokens * price.input_per_1m / 1e6 + c.output_tokens * price.output_per_1m / 1e6
    return round(total, 6)


class TrackedLLM(LLMClient):
    """Delegates to `inner` and records each completion (complete_json retries included)."""

    def __init__(self, inner: LLMClient, role: str, tracker: UsageTracker):
        super().__init__(model=inner.model, temperature=inner.default_temperature)
        self.inner = inner
        self.role = role
        self.tracker = tracker
        self.provider = inner.provider

    def _complete(self, *args, **kwargs) -> LLMResponse:  # pragma: no cover - complete() delegates
        raise NotImplementedError

    def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        try:
            response = self.inner.complete(
                system, messages, temperature=temperature, max_tokens=max_tokens
            )
        except LLMError as e:
            self.tracker.record(CallRecord(self.role, self.model, 0, 0, 0.0, type(e).__name__))
            raise
        self.tracker.record(
            CallRecord(
                self.role,
                self.model,
                response.input_tokens,
                response.output_tokens,
                response.latency_s,
                api_model=response.model,
            )
        )
        return response
