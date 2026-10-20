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


def format_amount(amount: float) -> str:
    """The one allowed amount format, e.g. $3,000.00."""
    return f"${amount:,.2f}"


def find_money(text: str) -> list[str]:
    return [m.group(0).rstrip(",") for m in _MONEY_RE.finditer(text)]


def check_final_text(
    text: str, outcome: EligibilityOutcome, messages: Messages | None = None
) -> list[str]:
    """Violations in `text` for this outcome; an empty list means the text is safe to send."""
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
