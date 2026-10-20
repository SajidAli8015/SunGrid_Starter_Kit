"""Run questions through the agent (pipeline mode) and build one record per question.

Each question gets a fresh Session; its turns run in order. Questions run in parallel across worker
threads, each with its own agent (agents are not thread-safe). A crash or provider failure on one
question is recorded as `error` for that question and never stops the run.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from sungrid_copilot.agent import AgentResponse, CopilotAgent, Outcome, Session
from sungrid_copilot.evaluation.checks import run_checks
from sungrid_copilot.evaluation.schema import Question

AgentFactory = Callable[[], CopilotAgent]
_ERROR_DETAIL_CHARS = 300


def stem_of(chunk_id: str) -> str:
    return chunk_id.split("::", 1)[0]


def stems_from_labels(labels: list[str], title_to_stem: dict[str, str]) -> list[str]:
    """Doc stems for "title > section" source labels."""
    stems = [title_to_stem.get(label.split(" > ", 1)[0], f"?{label}") for label in labels]
    return list(dict.fromkeys(stems))


def _turn_record(say: str, expect_outcome: str | None, r: AgentResponse) -> dict:
    d = r.details
    return {
        "say": say,
        "expect_outcome": expect_outcome,
        "outcome": r.outcome.value,
        "text": r.text,
        "escalated": r.escalated,
        "escalation_reason": r.escalation_reason,
        "sources": r.sources,
        "category": d.get("category"),
        "confidence": d.get("confidence"),
        "service_called": d.get("service_called", False),
        "gate_verdict": d.get("gate_verdict"),
        "guard_violations": d.get("guard_violations") or [],
        "llm_calls": d.get("llm_calls", []),
        "tokens_in": d.get("tokens_in", 0),
        "tokens_out": d.get("tokens_out", 0),
        "latency_ms": d.get("latency_ms", 0.0),
        "estimated_cost_usd": d.get("estimated_cost_usd"),
        "details": d,
        "trace": [asdict(step) for step in r.trace],
    }


def build_record(q: Question, turns: list[dict], title_to_stem: dict[str, str], error: str | None) -> dict:
    """Aggregate a question's turns. Checks apply to the final turn (see eval/README.md)."""
    final = turns[-1] if turns else {}
    d = final.get("details", {})
    classified = [t for t in turns if t.get("category")]
    last_classified = classified[-1] if classified else {}
    retrieved = [
        {"stem": stem_of(h["chunk_id"]), "chunk_id": h["chunk_id"], "score": h["score"]}
        for h in d.get("retrieved", [])
    ]
    costs = [t.get("estimated_cost_usd") for t in turns]
    if error is None and final.get("outcome") == Outcome.SERVICE_UNAVAILABLE.value:
        error = f"provider failure: {final.get('escalation_reason')}"
    return {
        "id": q.id,
        "tags": q.tags,
        "error": error,
        "turns": [{k: v for k, v in t.items() if k != "details"} for t in turns],
        "final_text": final.get("text", ""),
        "outcome": final.get("outcome"),
        # The pending slot-filling path does not re-classify, so use the last classified turn.
        "category": last_classified.get("category"),
        "confidence": last_classified.get("confidence"),
        "filter_used": d.get("filter_used"),
        "fallback_reason": d.get("fallback_reason"),
        "margin": d.get("margin"),
        "retrieved": retrieved,
        "retrieved_stems": list(dict.fromkeys(h["stem"] for h in retrieved)),
        "cited_stems": stems_from_labels(final.get("sources", []), title_to_stem),
        "service_called": any(t.get("service_called") for t in turns),
        "gate_verdict": final.get("gate_verdict"),
        "escalated": final.get("escalated", False),
        "escalation_reason": final.get("escalation_reason"),
        "guard_violations": [v for t in turns for v in t.get("guard_violations", [])],
        "llm_calls": [c | {"turn": i + 1} for i, t in enumerate(turns) for c in t.get("llm_calls", [])],
        "llm_call_count": sum(len(t.get("llm_calls", [])) for t in turns),
        "tokens_in": sum(t.get("tokens_in", 0) for t in turns),
        "tokens_out": sum(t.get("tokens_out", 0) for t in turns),
        "latency_ms": round(sum(t.get("latency_ms", 0.0) for t in turns), 1),
        "estimated_cost_usd": (
            round(sum(costs), 6) if costs and all(c is not None for c in costs) else None
        ),
    }


def run_question(agent: CopilotAgent, q: Question, title_to_stem: dict[str, str]) -> dict:
    session = Session()
    turns: list[dict] = []
    error = None
    try:
        for turn in q.turns:
            response = agent.handle(turn.say, session)
            turns.append(_turn_record(turn.say, turn.expect_outcome, response))
    except Exception as e:  # one broken question must not stop the run
        error = f"{type(e).__name__}: {str(e)[:_ERROR_DETAIL_CHARS]}"
    record = build_record(q, turns, title_to_stem, error)
    record["mode"] = "pipeline"
    record["checks"], record["check_details"], record["auto_pass"] = run_checks(q, record)
    return record


def run_eval(
    questions: list[Question],
    agent_factory: AgentFactory,
    title_to_stem: dict[str, str],
    *,
    workers: int = 3,
    repeat: int = 1,
) -> list[dict]:
    """Records in question order, repeats grouped (`repeat` field, starting at 1)."""
    local = threading.local()
    # Building agents concurrently races inside Chroma's client setup ("Could not connect to
    # tenant default_tenant"), so construction is serialised; queries then run in parallel.
    setup_lock = threading.Lock()

    def work(item: tuple[int, Question]) -> dict:
        rep, q = item
        try:
            if not hasattr(local, "agent"):
                with setup_lock:
                    local.agent = agent_factory()
        except Exception as e:  # e.g. the index or service could not be loaded
            record = build_record(q, [], title_to_stem, f"agent setup failed: {type(e).__name__}: {e}")
            record["mode"] = "pipeline"
            record["checks"], record["check_details"], record["auto_pass"] = run_checks(q, record)
            return record | {"repeat": rep}
        return run_question(local.agent, q, title_to_stem) | {"repeat": rep}

    items = [(rep, q) for rep in range(1, repeat + 1) for q in questions]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(work, items))
