"""Deterministic member-facing text for an eligibility outcome, from messages.yaml (no LLM)."""

from __future__ import annotations

from sungrid_copilot.config import load_settings
from sungrid_copilot.eligibility.adapter import InvalidInput, ToolError
from sungrid_copilot.eligibility.flow import (
    Decision,
    EligibilityOutcome,
    NeedsInfo,
    TierNotHousehold,
)
from sungrid_copilot.eligibility.gate import Verdict
from sungrid_copilot.eligibility.guard import format_amount
from sungrid_copilot.eligibility.questions import build_clarifying_question
from sungrid_copilot.eligibility.slots import SLOT_ORDER
from sungrid_copilot.messages import Messages

REQUIRED_KEYS = [
    "ask_missing_intro",
    *(f"q_{slot}" for slot in SLOT_ORDER),
    "ineligible",
    "eligible_preliminary",
    "eligible_caveat",
    "tier_not_household",
    "invalid_input",
    "tool_error",
]


def load_messages(messages: Messages | None = None) -> Messages:
    messages = messages or Messages.load(load_settings().messages.resolved_file)
    messages.require(REQUIRED_KEYS)
    return messages


def render(outcome: EligibilityOutcome, messages: Messages | None = None) -> str:
    messages = load_messages(messages)
    match outcome:
        case NeedsInfo(missing=missing):
            return build_clarifying_question(list(missing), messages)
        case TierNotHousehold(tier=tier):
            return messages.text("tier_not_household", tier=messages.lookup("tiers", tier))
        case InvalidInput(field=field, problem=problem):
            return messages.text(
                "invalid_input",
                field=messages.lookup("fields", field),
                problem=messages.lookup("problems", problem),
            )
        case Decision(decision=d) if d.verdict is Verdict.INELIGIBLE:
            # Built from the service's reason only: no amount can appear here.
            return messages.text("ineligible", reason=d.reason)
        case Decision(decision=d) if d.verdict is Verdict.ELIGIBLE_PRELIMINARY:
            first = messages.text("eligible_preliminary", amount=format_amount(d.amount))
            return f"{first}\n\n{messages.text('eligible_caveat')}"
        case ToolError():
            return messages.text("tool_error")
    raise TypeError(f"Unknown eligibility outcome: {outcome!r}")
