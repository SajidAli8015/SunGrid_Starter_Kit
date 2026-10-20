"""The hard eligibility gate: pure Python, no LLM.

Maps the service's raw output to a decision. Only ELIGIBLE_PRELIMINARY can carry an amount; a
decision with any other verdict cannot even be constructed with one. Anything malformed or
contradictory is TOOL_ERROR, never a guess.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sungrid_copilot.eligibility.guard import find_money


class Verdict(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE_PRELIMINARY = "ELIGIBLE_PRELIMINARY"
    TOOL_ERROR = "TOOL_ERROR"


@dataclass(frozen=True)
class GateDecision:
    verdict: Verdict
    reason: str | None = None  # the service's reason (INELIGIBLE / ELIGIBLE_PRELIMINARY)
    amount: float | None = None  # ELIGIBLE_PRELIMINARY only
    problem: str | None = None  # why the result was rejected (TOOL_ERROR only)

    def __post_init__(self) -> None:
        if self.verdict is Verdict.ELIGIBLE_PRELIMINARY:
            if self.amount is None or not self.amount > 0:
                raise ValueError("ELIGIBLE_PRELIMINARY needs a positive amount")
        elif self.amount is not None:
            raise ValueError(f"{self.verdict.value} must not carry an amount")


def _malformed(problem: str) -> GateDecision:
    return GateDecision(Verdict.TOOL_ERROR, problem=problem)


def evaluate(raw: Any) -> GateDecision:
    if not isinstance(raw, Mapping):
        return _malformed("result is not a mapping")
    missing = [k for k in ("eligible", "reason", "estimated_rebate_usd") if k not in raw]
    if missing:
        return _malformed(f"missing keys: {', '.join(missing)}")

    eligible, reason, amount = raw["eligible"], raw["reason"], raw["estimated_rebate_usd"]
    if type(eligible) is not bool:
        return _malformed("'eligible' is not a bool")
    if not isinstance(reason, str) or not reason.strip():
        return _malformed("'reason' is not a non-empty string")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return _malformed("'estimated_rebate_usd' is not a number")
    if not math.isfinite(amount) or amount < 0:
        return _malformed("'estimated_rebate_usd' is not a finite non-negative number")

    if not eligible:
        if amount > 0:
            return _malformed("eligible=False with an amount above 0")
        if find_money(reason):
            # The reason is shown to the member verbatim; it must not smuggle in an amount.
            return _malformed("reason for an ineligible result contains a money amount")
        return GateDecision(Verdict.INELIGIBLE, reason=reason.strip())

    if amount <= 0:
        return _malformed("eligible=True with an amount of 0 or less")
    return GateDecision(Verdict.ELIGIBLE_PRELIMINARY, reason=reason.strip(), amount=float(amount))
