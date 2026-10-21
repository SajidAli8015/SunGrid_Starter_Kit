"""Output guard: checks the final member-facing text against the eligibility outcome.

The next task lets an LLM append grounded "what happens next" text after the deterministic part;
if this guard reports any violation, the caller falls back to the deterministic text alone.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sungrid_copilot.config import load_settings
from sungrid_copilot.messages import Messages

if TYPE_CHECKING:
    from sungrid_copilot.eligibility.flow import EligibilityOutcome

# "$3,000.00", "$ 500", "USD 500", "500 USD", "500 dollars"
_MONEY_RE = re.compile(
    r"\$\s*\d[\d,]*(?:\.\d+)?"
    r"|\bUSD\s*\d[\d,]*(?:\.\d+)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:USD|dollars?)\b",
    re.IGNORECASE,
)
# Checked only in the LLM-written part of a non-eligible reply, where amounts can appear without a
# currency sign: "4,000", "4000", "3k", "40 cents", "0.40 per watt". Ordinary short numbers such as
# "30 days" pass; a year or a percentage of 3+ digits fails safe (the LLM text is dropped).
_NUMBER_RE = re.compile(
    r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])"  # digit groups with separators: 4,000
    r"|(?<![\d.,])\d{3,}(?![\d,])"  # 3+ bare digits: 4000
    r"|\d+(?:\.\d+)?\s*(?:k\b|cents?\b|¢|(?:/|per\s+)?watts?\b|/\s*W\b)",  # 3k, 40 cents, 0.40 per watt
    re.IGNORECASE,
)


def format_amount(amount: float) -> str:
    """The one allowed amount format, e.g. $3,000.00."""
    return f"${amount:,.2f}"


def find_money(text: str) -> list[str]:
    return [m.group(0).rstrip(",") for m in _MONEY_RE.finditer(text)]


def find_numbers(text: str) -> list[str]:
    return [m.group(0) for m in _NUMBER_RE.finditer(text)]


def check_final_text(
    text: str,
    outcome: EligibilityOutcome,
    messages: Messages | None = None,
    *,
    llm_text: str | None = None,
) -> list[str]:
    """Violations in `text` for this outcome; an empty list means the text is safe to send.

    `llm_text` is the LLM-written part of `text`. In a non-eligible reply it is also checked for
    amounts written without a currency sign; the deterministic part is not, since its numbers (the
    service's reason, such as "3kW-10kW") are fixed text.
    """
    from sungrid_copilot.eligibility.flow import Decision
    from sungrid_copilot.eligibility.gate import Verdict

    eligible = (
        isinstance(outcome, Decision) and outcome.decision.verdict is Verdict.ELIGIBLE_PRELIMINARY
    )
    if not eligible:
        found = find_money(text)
        violations = [f"amount in a non-eligible reply: {m}" for m in found]
        if "$" in text and not found:
            violations.append("'$' in a non-eligible reply")
        if llm_text:
            violations += [
                f"number in the LLM text of a non-eligible reply: {n}" for n in find_numbers(llm_text)
            ]
        return violations

    messages = messages or Messages.load(load_settings().messages.resolved_file)
    allowed = format_amount(outcome.decision.amount)
    violations = [
        f"amount other than the service's {allowed}: {m}" for m in find_money(text) if m != allowed
    ]
    if allowed not in text:
        violations.append(f"the service's amount {allowed} is missing")
    if messages.text("eligible_caveat") not in text:
        violations.append("the preliminary-check caveat is missing")
    return violations
