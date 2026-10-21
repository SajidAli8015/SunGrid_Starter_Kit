"""The Copilot agent: a bounded, fixed flow where the LLM chooses and code enforces.

classify -> retrieve -> (guarded decline) -> grounded answer, or the eligibility flow.
The eligibility service is reached only through `run_eligibility`. Member-facing fixed text comes
from config/messages.yaml. Sessions live in memory only and are never persisted.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum

from sungrid_copilot.answer import AnswerComposer, AnswerResult
from sungrid_copilot.categories import load_categories
from sungrid_copilot.classify import ClassificationResult, Classifier
from sungrid_copilot.config import Settings
from sungrid_copilot.eligibility.adapter import EligibilityAdapter, InvalidInput, ToolError
from sungrid_copilot.eligibility.flow import (
    Decision,
    EligibilityOutcome,
    NeedsInfo,
    TierNotHousehold,
    run_eligibility,
)
from sungrid_copilot.eligibility.gate import Verdict
from sungrid_copilot.eligibility.guard import check_final_text, find_money
from sungrid_copilot.eligibility.render import load_messages, render
from sungrid_copilot.eligibility.slots import SLOT_ORDER, EligibilitySlots, SlotExtractor
from sungrid_copilot.llm import LLMContentFilterError, LLMError, get_llm_client
from sungrid_copilot.messages import Messages
from sungrid_copilot.querylog import QueryLogger
from sungrid_copilot.kb.store import SearchHit
from sungrid_copilot.retrieval import RetrievalResult, Retriever
from sungrid_copilot.usage import TrackedLLM, UsageTracker, estimate_cost

AGENT_MESSAGE_KEYS = [
    "out_of_scope",
    "content_filter",
    "temporarily_unavailable",
    "abstain",
    "escalation_notice",
    "too_many_clarifications",
    "sources_header",
    "empty_message",
]


class Outcome(str, Enum):
    ANSWERED = "answered"
    ABSTAINED = "abstained"
    DECLINED_OUT_OF_SCOPE = "declined_out_of_scope"
    DECLINED_CONTENT_FILTER = "declined_content_filter"
    NEEDS_INFO = "needs_info"
    TOO_MANY_CLARIFICATIONS = "too_many_clarifications"
    ELIGIBLE_PRELIMINARY = "eligible_preliminary"
    INELIGIBLE = "ineligible"
    TIER_NOT_HOUSEHOLD = "tier_not_household"
    INVALID_INPUT = "invalid_input"
    TOOL_ERROR = "tool_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    EMPTY_MESSAGE = "empty_message"


@dataclass
class TraceStep:
    name: str
    summary: str = ""
    ms: float = 0.0


@dataclass(frozen=True)
class AgentResponse:
    text: str  # the full member-facing reply, sources block included
    sources: list[str]  # "doc title > section"
    outcome: Outcome
    escalated: bool
    escalation_reason: str | None
    trace: list[TraceStep]
    details: dict  # the log record for this message (no member text or slot values)


@dataclass
class Session:
    """In-memory conversation state. Never persisted."""

    slots: EligibilitySlots = field(default_factory=EligibilitySlots)
    pending_eligibility: bool = False
    clarification_turns: int = 0
    # The last eligibility verdict in this session: later knowledge answers must not hand an
    # ineligible (or non-household) member an amount the hard gate withheld.
    last_verdict: Outcome | None = None

    def finish_eligibility(self) -> None:
        self.pending_eligibility = False
        self.clarification_turns = 0


@dataclass
class _Run:
    """Scratch state for one handled message."""

    trace: list[TraceStep] = field(default_factory=list)
    log: dict = field(default_factory=dict)


class CopilotAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        classifier: Classifier,
        retriever: Retriever,
        composer: AnswerComposer,
        extractor: SlotExtractor,
        adapter: EligibilityAdapter,
        messages: Messages,
        usage: UsageTracker | None = None,
        logger: QueryLogger | None = None,
    ):
        self.settings = settings
        self.classifier = classifier
        self.retriever = retriever
        self.composer = composer
        self.extractor = extractor
        self.adapter = adapter
        self.messages = load_messages(messages)
        self.messages.require(AGENT_MESSAGE_KEYS)
        self.usage = usage or UsageTracker()
        self.logger = logger
        self.use_cache = settings.agent.use_llm_cache
        retriever.categories.require(settings.eligibility.next_steps.category)

    @classmethod
    def from_settings(cls, settings: Settings) -> CopilotAgent:
        usage = UsageTracker()

        def client(role: str) -> TrackedLLM:
            return TrackedLLM(get_llm_client(role, settings), role, usage)

        # LLM caches hold the member's text on disk, so they are off unless configured.
        cache = settings.agent.use_llm_cache
        classifier = Classifier(
            client("classifier"),
            load_categories(settings.categories.resolved_file),
            max_tokens=settings.classifier.max_tokens,
            cache_dir=settings.classifier.resolved_cache_dir if cache else None,
        )
        extractor = SlotExtractor(
            client("extractor"),
            max_tokens=settings.eligibility.extractor_max_tokens,
            cache_dir=settings.eligibility.resolved_cache_dir if cache else None,
        )
        return cls(
            settings=settings,
            classifier=classifier,
            retriever=Retriever.from_settings(settings),
            composer=AnswerComposer.from_settings(settings, client=client("answerer")),
            extractor=extractor,
            adapter=EligibilityAdapter.from_settings(settings),
            messages=Messages.load(settings.messages.resolved_file),
            usage=usage,
            logger=QueryLogger(
                settings.logging.resolved_path,
                include_query_text=settings.logging.include_query_text,
            ),
        )

    # ------------------------------------------------------------------ entry point

    def handle(self, user_text: str, session: Session) -> AgentResponse:
        self.usage.reset()
        run = _Run()
        start = time.perf_counter()
        if not user_text.strip():  # nothing to classify; pending eligibility state is kept
            response = self._reply(run, Outcome.EMPTY_MESSAGE, self.messages.text("empty_message"))
            return self._finish(user_text, run, response, start)
        try:
            response = self._handle(user_text, session, run)
        except LLMContentFilterError:
            session.finish_eligibility()
            response = self._reply(run, Outcome.DECLINED_CONTENT_FILTER, self.messages.text("content_filter"))
        except LLMError as e:
            # No unclassified fallback: without the LLM there is no safe answer.
            session.finish_eligibility()
            response = self._reply(
                run,
                Outcome.SERVICE_UNAVAILABLE,
                self.messages.text("temporarily_unavailable"),
                escalate="llm_error",
                detail=type(e).__name__,
            )
        except Exception as e:
            # Any other failure (index, embedder, config, a bug): no answer, a person follows up.
            # Only the exception type is kept; its message could hold the member's text.
            session.finish_eligibility()
            response = self._reply(
                run,
                Outcome.SERVICE_UNAVAILABLE,
                self.messages.text("temporarily_unavailable"),
                escalate="internal_error",
                detail=type(e).__name__,
            )
        return self._finish(user_text, run, response, start)

    def _handle(self, text: str, session: Session, run: _Run) -> AgentResponse:
        if session.pending_eligibility:
            with self._step(run, "extract_slots") as step:
                merged = self.extractor.extract(text, prior=session.slots, use_cache=self.use_cache)
                added = [k for k in SLOT_ORDER if getattr(merged, k) != getattr(session.slots, k)]
                step.summary = f"pending; updated: {added or 'nothing'}"
            run.log["pending_eligibility"] = True
            if added:
                session.slots = merged
                return self._eligibility(session, run)
            session.pending_eligibility = False  # unrelated follow-up: handle as a new question

        with self._step(run, "classify") as step:
            classified = self.classifier.classify(text, use_cache=self.use_cache)
            label = classified.result
            step.summary = (
                f"{label.category} ({label.confidence:.2f}), "
                f"eligibility={label.needs_eligibility_check}, cached={classified.cached}"
            )
        run.log.update(
            category=label.category,
            confidence=label.confidence,
            needs_eligibility_check=label.needs_eligibility_check,
            classifier_cached=classified.cached,
        )

        with self._step(run, "retrieve") as step:
            retrieved = self.retriever.retrieve(text, label)
            declined = self.retriever.should_decline(label, retrieved)
            step.summary = _retrieval_summary(retrieved) + f", decline={declined}"
        run.log.update(_retrieval_log(retrieved), should_decline=declined)
        if declined:
            return self._reply(run, Outcome.DECLINED_OUT_OF_SCOPE, self.messages.text("out_of_scope"))

        if label.needs_eligibility_check:
            with self._step(run, "extract_slots") as step:
                session.slots = self.extractor.extract(text, prior=session.slots, use_cache=self.use_cache)
                step.summary = f"missing: {session.slots.missing() or 'none'}"
            return self._eligibility(session, run)
        return self._answer(text, retrieved, session, run)

    # ------------------------------------------------------------------ knowledge answers

    def _answer(
        self, question: str, retrieved: RetrievalResult, session: Session, run: _Run
    ) -> AgentResponse:
        with self._step(run, "compose_answer") as step:
            answer = self.composer.compose(question, retrieved.hits)
            step.summary = _answer_summary(answer)
        run.log["answer"] = _answer_log(answer)
        if not answer.supported:
            return self._reply(
                run,
                Outcome.ABSTAINED,
                self.messages.text("abstain"),
                escalate="abstained",
                detail=answer.problem or answer.review_reason,
            )
        if session.last_verdict in (Outcome.INELIGIBLE, Outcome.TIER_NOT_HOUSEHOLD):
            # Same rule as the hard gate, one turn later: no amount for a member who was refused.
            found = find_money(answer.text)
            run.log["guard_violations"] = [f"amount after a non-eligible verdict: {m}" for m in found]
            if found:
                return self._reply(
                    run,
                    Outcome.ABSTAINED,
                    self.messages.text("abstain"),
                    escalate="amount_after_non_eligible_verdict",
                )
        body = answer.text
        if answer.needs_human_review:
            reason = answer.review_reason or "flagged by the answer step"
            body += "\n\n" + self.messages.text("escalation_notice", reason=reason)
            return self._reply(
                run, Outcome.ANSWERED, body, answer.source_labels,
                escalate="needs_human_review", detail=reason,
            )
        return self._reply(run, Outcome.ANSWERED, body, answer.source_labels)

    # ------------------------------------------------------------------ eligibility

    def _eligibility(self, session: Session, run: _Run) -> AgentResponse:
        with self._step(run, "eligibility") as step:
            outcome = run_eligibility(session.slots, self.adapter)
            step.summary = type(outcome).__name__
        # Only a Decision or a ToolError means the service was actually called (see flow.py).
        run.log.update(
            service_called=isinstance(outcome, (Decision, ToolError)),
            eligibility_outcome=type(outcome).__name__,
            gate_verdict=outcome.decision.verdict.value if isinstance(outcome, Decision) else None,
        )
        deterministic = render(outcome, self.messages)

        if isinstance(outcome, (NeedsInfo, InvalidInput)):
            # Asking for missing details and asking to correct an invalid one share the limit.
            if session.clarification_turns >= self.settings.agent.max_clarification_turns:
                session.finish_eligibility()
                return self._reply(
                    run, Outcome.TOO_MANY_CLARIFICATIONS,
                    self.messages.text("too_many_clarifications"),
                    escalate="too_many_clarifications",
                )
            session.pending_eligibility = True  # the member can answer or correct; no service call
            session.clarification_turns += 1
            result = Outcome.NEEDS_INFO if isinstance(outcome, NeedsInfo) else Outcome.INVALID_INPUT
            return self._reply(run, result, deterministic)

        session.finish_eligibility()
        if isinstance(outcome, TierNotHousehold):
            session.last_verdict = Outcome.TIER_NOT_HOUSEHOLD
        elif isinstance(outcome, Decision):
            eligible = outcome.decision.verdict is Verdict.ELIGIBLE_PRELIMINARY
            session.last_verdict = Outcome.ELIGIBLE_PRELIMINARY if eligible else Outcome.INELIGIBLE
        if isinstance(outcome, TierNotHousehold):
            return self._reply(
                run, Outcome.TIER_NOT_HOUSEHOLD, deterministic, escalate="tier_not_household"
            )
        if isinstance(outcome, ToolError):
            return self._reply(run, Outcome.TOOL_ERROR, deterministic, escalate=f"tool_error:{outcome.kind}")
        return self._decision(outcome, deterministic, run)

    def _decision(self, outcome: Decision, deterministic: str, run: _Run) -> AgentResponse:
        eligible = outcome.decision.verdict is Verdict.ELIGIBLE_PRELIMINARY
        result = Outcome.ELIGIBLE_PRELIMINARY if eligible else Outcome.INELIGIBLE
        next_steps = self.settings.eligibility.next_steps
        queries = next_steps.queries.get("eligible" if eligible else "ineligible") or []
        if not queries:
            return self._reply(run, result, deterministic)

        # "What happens next" from the KB. The composer sees fixed questions, never the member's
        # text, slots or the service's amount.
        with self._step(run, "next_steps") as step:
            label = ClassificationResult(
                category=next_steps.category, confidence=1.0,
                needs_eligibility_check=False, rationale="next-steps lookup",
            )
            hits = _merge_hits(
                [self.retriever.retrieve(q, label).hits for q in queries],
                self.settings.retrieval.top_k,
            )
            question = " ".join(queries)
            try:
                answer = self.composer.compose(question, hits, focus=next_steps.focus)
            except LLMError as e:  # keep the deterministic decision
                answer = None
                step.summary = f"composer failed: {type(e).__name__}"
            else:
                step.summary = _answer_summary(answer)
        run.log["next_steps_retrieved"] = [
            {"chunk_id": h.chunk.chunk_id, "score": round(h.score, 4)} for h in hits
        ]
        if answer is None or not answer.supported:
            return self._reply(run, result, deterministic)

        candidate = self._with_sources(f"{deterministic}\n\n{answer.text}", answer.source_labels)
        with self._step(run, "guard") as step:
            violations = check_final_text(candidate, outcome, self.messages, llm_text=answer.text)
            step.summary = f"violations: {violations}" if violations else "ok"
        run.log["guard_violations"] = violations
        if violations:
            return self._reply(run, result, deterministic)  # drop everything the LLM wrote
        return _response(result, candidate, answer.source_labels, run)

    # ------------------------------------------------------------------ helpers

    def _with_sources(self, body: str, sources: list[str]) -> str:
        if not sources:
            return body
        lines = "\n".join(f"- {s}" for s in sources)
        return f"{body}\n\n{self.messages.text('sources_header')}\n{lines}"

    def _reply(
        self,
        run: _Run,
        outcome: Outcome,
        body: str,
        sources: list[str] | None = None,
        *,
        escalate: str | None = None,
        detail: str | None = None,
    ) -> AgentResponse:
        sources = sources or []
        run.log["escalation_code"] = escalate  # a fixed code, never member text
        reason = None if escalate is None else (f"{escalate}: {detail}" if detail else escalate)
        return _response(outcome, self._with_sources(body, sources), sources, run, reason)

    @contextmanager
    def _step(self, run: _Run, name: str) -> Iterator[TraceStep]:
        step = TraceStep(name)
        run.trace.append(step)
        start = time.perf_counter()
        try:
            yield step
        finally:
            step.ms = round((time.perf_counter() - start) * 1000, 1)

    def _finish(self, query: str, run: _Run, response: AgentResponse, start: float) -> AgentResponse:
        calls = self.usage.calls
        run.log.update(
            outcome=response.outcome.value,
            escalated=response.escalated,
            llm_call_count=len(calls),
            llm_calls=self.usage.by_call(),
            tokens_in=self.usage.input_tokens,
            tokens_out=self.usage.output_tokens,
            step_latency_ms={s.name: s.ms for s in run.trace},
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            estimated_cost_usd=estimate_cost(
                calls, self.settings.llm.provider, self.settings.pricing,
                self.settings.pricing_model_map,
            ),
        )
        run.log.setdefault("service_called", False)
        run.log.setdefault("escalation_code", None)
        record = self.logger.write(query, run.log) if self.logger else dict(run.log)
        return AgentResponse(
            text=response.text,
            sources=response.sources,
            outcome=response.outcome,
            escalated=response.escalated,
            escalation_reason=response.escalation_reason,
            trace=run.trace,
            details=record,
        )


def _response(
    outcome: Outcome, text: str, sources: list[str], run: _Run, reason: str | None = None
) -> AgentResponse:
    return AgentResponse(
        text=text,
        sources=sources,
        outcome=outcome,
        escalated=reason is not None,
        escalation_reason=reason,
        trace=run.trace,
        details={},
    )


def _merge_hits(results: list[list[SearchHit]], top_k: int) -> list[SearchHit]:
    """Union of several searches: best score per chunk, highest first."""
    best: dict[str, SearchHit] = {}
    for hits in results:
        for hit in hits:
            if hit.chunk.chunk_id not in best or hit.score > best[hit.chunk.chunk_id].score:
                best[hit.chunk.chunk_id] = hit
    return sorted(best.values(), key=lambda h: h.score, reverse=True)[:top_k]


def _retrieval_log(r: RetrievalResult) -> dict:
    return {
        "filter_used": r.filter_used,
        "fallback_reason": r.fallback_reason,
        "margin": None if r.margin is None else round(r.margin, 4),
        "unfiltered_top_score": None if r.unfiltered_top_score is None else round(r.unfiltered_top_score, 4),
        "retrieved": [{"chunk_id": h.chunk.chunk_id, "score": round(h.score, 4)} for h in r.hits],
    }


def _retrieval_summary(r: RetrievalResult) -> str:
    margin = "-" if r.margin is None else f"{r.margin:.3f}"
    return (
        f"filter={r.filter_used or 'none'}, fallback={r.fallback_reason or '-'}, margin={margin}, "
        f"top1={r.unfiltered_top_score or 0:.3f}"
    )


def _answer_summary(a: AnswerResult) -> str:
    if not a.supported:
        return f"unsupported ({a.problem or a.review_reason or 'no reason'})"
    return f"supported, cites {len(a.citations)}, review={a.needs_human_review}"


def _answer_log(a: AnswerResult) -> dict:
    return {
        "supported": a.supported,
        "cited": [c.chunk_id for c in a.citations],
        "needs_human_review": a.needs_human_review,
        "problem": a.problem,
    }
