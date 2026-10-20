"""One deterministic clarifying question listing every missing slot (no LLM)."""

from __future__ import annotations

from sungrid_copilot.config import load_settings
from sungrid_copilot.messages import Messages


def build_clarifying_question(missing: list[str], messages: Messages | None = None) -> str:
    if not missing:
        raise ValueError("Nothing is missing; no question to ask.")
    messages = messages or Messages.load(load_settings().messages.resolved_file)
    lines = [messages.text("ask_missing_intro")]
    lines += [f"- {messages.text(f'q_{slot}')}" for slot in missing]
    return "\n".join(lines)
