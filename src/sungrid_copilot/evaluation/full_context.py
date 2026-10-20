"""Full-context BASELINE: every KB chunk in one prompt, no classification, filter or retrieval.

A comparison point for the pipeline, not the product. Eligibility and non_relevant questions are
skipped (they exercise the tool and the decline, which this baseline does not have). Only the text
checks are scored; retrieval, category, tool and escalation checks are N/A.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from sungrid_copilot.answer import AnswerComposer
from sungrid_copilot.evaluation.checks import run_checks
from sungrid_copilot.evaluation.runner import stems_from_labels
from sungrid_copilot.evaluation.schema import Question
from sungrid_copilot.kb.store import Chunk
from sungrid_copilot.llm import LLMError
from sungrid_copilot.messages import Messages
from sungrid_copilot.usage import CallRecord, UsageTracker

SKIP_TAGS = {"eligibility", "non_relevant"}
TEXT_CHECKS = {"contains_ok", "not_contains_ok", "hard_gate_ok"}
ComposerFactory = Callable[[], tuple[AnswerComposer, UsageTracker]]
CostFn = Callable[[list[CallRecord]], float | None]


def skip_reason(q: Question) -> str | None:
    hit = SKIP_TAGS.intersection(q.tags)
    return f"tagged {sorted(hit)}: not applicable to the full-context baseline" if hit else None


def run_full_context_question(
    composer: AnswerComposer,
    usage: UsageTracker,
    q: Question,
    chunks: list[Chunk],
    messages: Messages,
    title_to_stem: dict[str, str],
    cost_fn: CostFn | None = None,
) -> dict:
    record: dict = {"id": q.id, "tags": q.tags, "mode": "full-context", "error": None}
    if reason := skip_reason(q):
        return record | {"skipped": reason, "checks": {}, "check_details": {}, "auto_pass": None}
    question = " ".join(t.say for t in q.turns)  # single-turn in practice
    usage.reset()
    try:
        answer = composer.compose(question, chunks)
    except LLMError as e:
        answer, record["error"] = None, f"provider failure: {type(e).__name__}"
    if answer is not None and answer.supported:
        text, outcome = answer.text, "answered"
        sources = answer.source_labels
    else:
        text, outcome, sources = messages.text("abstain"), "abstained", []
    calls = usage.by_call()
    record.update(
        skipped=None,
        outcome=outcome,
        final_text=text,
        turns=[{"say": question, "outcome": outcome, "text": text}],
        cited_stems=stems_from_labels(sources, title_to_stem),
        escalated=bool(answer is None or answer.needs_human_review or not answer.supported),
        llm_calls=calls,
        llm_call_count=len(calls),
        tokens_in=usage.input_tokens,
        tokens_out=usage.output_tokens,
        latency_ms=round(sum(c["latency_s"] for c in calls) * 1000, 1),
        estimated_cost_usd=cost_fn(usage.calls) if cost_fn else None,
    )
    record["checks"], record["check_details"], record["auto_pass"] = run_checks(
        q, record, only=TEXT_CHECKS
    )
    return record


def run_full_context(
    questions: list[Question],
    composer_factory: ComposerFactory,
    chunks: list[Chunk],
    messages: Messages,
    title_to_stem: dict[str, str],
    *,
    workers: int = 3,
    cost_fn: CostFn | None = None,
) -> list[dict]:
    local = threading.local()
    setup_lock = threading.Lock()

    def work(q: Question) -> dict:
        if not hasattr(local, "composer"):
            with setup_lock:
                local.composer, local.usage = composer_factory()
        return run_full_context_question(
            local.composer, local.usage, q, chunks, messages, title_to_stem, cost_fn
        ) | {"repeat": 1}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(work, questions))
