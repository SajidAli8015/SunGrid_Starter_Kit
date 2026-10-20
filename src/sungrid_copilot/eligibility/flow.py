"""Deterministic eligibility flow (no LLM): ask, refuse to check, or call the service once."""

from __future__ import annotations

from dataclasses import dataclass

from sungrid_copilot.eligibility.adapter import (
    EligibilityAdapter,
    InvalidInput,
    RawResult,
    ToolError,
)
from sungrid_copilot.eligibility.gate import GateDecision, Verdict, evaluate
from sungrid_copilot.eligibility.slots import EligibilitySlots


@dataclass(frozen=True)
class NeedsInfo:
    missing: tuple[str, ...]
    escalate: bool = False


@dataclass(frozen=True)
class TierNotHousehold:
    tier: str
    escalate: bool = True  # tier-transfer wording in the KB is ambiguous: a human reviews it


@dataclass(frozen=True)
class Decision:
    decision: GateDecision  # INELIGIBLE or ELIGIBLE_PRELIMINARY only
    escalate: bool = False


EligibilityOutcome = NeedsInfo | TierNotHousehold | InvalidInput | Decision | ToolError


def run_eligibility(slots: EligibilitySlots, adapter: EligibilityAdapter) -> EligibilityOutcome:
    # A known non-household tier needs no further questions: the rebate is not for that tier.
    if slots.member_tier is not None and slots.member_tier != "household":
        return TierNotHousehold(slots.member_tier)
    missing = slots.missing()
    if missing:
        return NeedsInfo(tuple(missing))

    result = adapter.check(slots)
    if not isinstance(result, RawResult):
        return result  # InvalidInput or ToolError
    decision = evaluate(result.raw)
    if decision.verdict is Verdict.TOOL_ERROR:
        return ToolError("malformed_result", decision.problem or "")
    return Decision(decision)
