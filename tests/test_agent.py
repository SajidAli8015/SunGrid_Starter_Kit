"""Agent end to end, offline: fake LLM per role, hash embedder over a temp Chroma KB, real stub."""

import json

import pytest
import stub_tools

from kb_helpers import entry, write_kb
from sungrid_copilot.agent import CopilotAgent, Outcome, Session
from sungrid_copilot.answer import AnswerComposer
from sungrid_copilot.categories import load_categories
from sungrid_copilot.classify import Classifier
from sungrid_copilot.config import Settings, load_settings
from sungrid_copilot.eligibility.adapter import EligibilityAdapter
from sungrid_copilot.eligibility.slots import EligibilitySlots, SlotExtractor
from sungrid_copilot.kb.embeddings import HashEmbedder
from sungrid_copilot.kb.ingest import ingest
from sungrid_copilot.llm import LLMContentFilterError, LLMError
from sungrid_copilot.llm.fake import FakeLLMClient
from sungrid_copilot.messages import Messages
from sungrid_copilot.querylog import QueryLogger
from sungrid_copilot.retrieval import Retriever
from sungrid_copilot.usage import TrackedLLM, UsageTracker

REAL = load_settings()
CATEGORIES = load_categories(REAL.categories.resolved_file)
MESSAGES = Messages.load(REAL.messages.resolved_file)

DOCS = {
    "rebate.md": (
        "# Rebate Program\n## Appeals\nMembers may appeal a rebate determination within 30 days.\n"
        "## Documentation\nApplicants submit proof of installer approval and an income attestation.\n"
    ),
    "faults.md": "# Fault Codes\n## E07\nE07 ground fault detected. Installer inspection required.\n",
    "bills.md": "# Bills\n## Charges\nMonthly bill charges explained.\n",
}
FULL_SLOTS = {
    "household_zip": "94103",
    "annual_income_usd": 85000,
    "system_size_kw": 7.5,
    "installer_approved": True,
    "member_tier": "household",
}
EMPTY_SLOTS = "{}"


def q(text):  # classifier/composer user message key (never matches a system prompt)
    return f"<question>\n{text}\n</question>"


def m(text):  # extractor user message key
    return f"<message>\n{text}\n</message>"


def label(category, confidence=0.9, eligibility=False):
    return json.dumps(
        {"category": category, "confidence": confidence,
         "needs_eligibility_check": eligibility, "rationale": "t"}
    )


def answer(text="Grounded answer.", cited=("S1",), supported=True, review=False, reason=None):
    return json.dumps(
        {"supported": supported, "answer": text, "cited_chunk_ids": list(cited),
         "needs_human_review": review, "review_reason": reason}
    )


class Spy:
    """Wraps the REAL stub and counts calls."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return stub_tools.check_rebate_eligibility(**kwargs)


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    root = tmp_path_factory.mktemp("kb")
    manifest, docs_dir = write_kb(
        root,
        DOCS,
        [
            entry("rebate.md", "incentive_rebate"),
            entry("faults.md", "technical_installation"),
            entry("bills.md", "billing_account"),
        ],
    )
    settings = Settings.model_validate(
        {
            "vector_store": {"path": root / "chroma", "collection": "agent_kb"},
            "ingestion": {"docs_dir": docs_dir, "manifest": manifest},
            "retrieval": {
                "top_k": 3,
                "classifier_min_conf": 0.6,
                "non_relevant_min_conf": 0.85,
                "fallback_margin": 0.04,
                "non_relevant_score_ceiling": 0.4,  # hash-embedder scale
            },
            "eligibility": {
                "next_steps": {
                    "category": "incentive_rebate",
                    "focus": "Explain only the next steps. No dollar amounts.",
                    "queries": {
                        "ineligible": "How do I appeal a rebate determination?",
                        "eligible": "What documentation do applicants submit?",
                    },
                }
            },
        }
    )
    ingest(settings, HashEmbedder())
    return settings


class Harness:
    def __init__(self, settings, tmp_path, classifier, extractor, composer, *, include_text=False,
                 extractor_obj=None):
        self.usage = UsageTracker()
        self.classifier_llm, self.extractor_llm, self.composer_llm = classifier, extractor, composer
        self.spy = Spy()
        self.log_path = tmp_path / "logs" / "queries.jsonl"
        self.agent = CopilotAgent(
            settings=settings,
            classifier=Classifier(TrackedLLM(classifier, "classifier", self.usage), CATEGORIES),
            retriever=Retriever.from_settings(settings, embedder=HashEmbedder()),
            composer=AnswerComposer(TrackedLLM(composer, "answerer", self.usage)),
            extractor=extractor_obj or SlotExtractor(TrackedLLM(extractor, "extractor", self.usage)),
            adapter=EligibilityAdapter(self.spy),
            messages=MESSAGES,
            usage=self.usage,
            logger=QueryLogger(self.log_path, include_query_text=include_text),
        )
        self.session = Session()

    def ask(self, text):
        return self.agent.handle(text, self.session)

    def log_records(self):
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]


def harness(kb, tmp_path, classifier=None, extractor=None, composer=None, **kw):
    return Harness(
        kb,
        tmp_path,
        classifier if classifier is not None else FakeLLMClient({}),
        extractor if extractor is not None else FakeLLMClient({}),
        composer if composer is not None else FakeLLMClient({}),
        **kw,
    )


class Raising(FakeLLMClient):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def _complete(self, *args, **kwargs):
        self.calls.append(None)
        raise self.exc


# --------------------------------------------------------------------------- knowledge answers


def test_knowledge_answer_cites_retrieved_chunks(kb, tmp_path):
    question = "How are monthly bill charges explained?"
    h = harness(
        kb, tmp_path,
        classifier=FakeLLMClient({q(question): label("billing_account")}),
        composer=FakeLLMClient({q(question): answer("Charges are explained monthly.")}),
    )
    r = h.ask(question)
    assert r.outcome is Outcome.ANSWERED and not r.escalated
    assert r.sources == ["Bills > Charges"]
    assert r.text.endswith("Sources:\n- Bills > Charges")
    sent = h.composer_llm.calls[0].messages[0]["content"]
    assert "[S1] Bills > Charges" in sent and "Monthly bill charges explained." in sent
    assert h.spy.calls == []


def test_unsupported_answer_abstains_and_escalates(kb, tmp_path):
    question = "What is the income threshold?"
    h = harness(
        kb, tmp_path,
        classifier=FakeLLMClient({q(question): label("incentive_rebate")}),
        composer=FakeLLMClient({q(question): answer("", cited=(), supported=False)}),
    )
    r = h.ask(question)
    assert r.outcome is Outcome.ABSTAINED and r.escalated
    assert r.text == MESSAGES.text("abstain")
    assert r.sources == []


@pytest.mark.parametrize("bad", [answer(cited=()), answer(cited=("S9",)), answer(cited=("06_x::00",))])
def test_ungrounded_answer_is_retried_once_then_abstains(kb, tmp_path, bad):
    question = "How are monthly bill charges explained?"
    composer = FakeLLMClient([bad, bad])
    h = harness(kb, tmp_path, classifier=FakeLLMClient({q(question): label("billing_account")}),
                composer=composer)
    r = h.ask(question)
    assert r.outcome is Outcome.ABSTAINED and r.escalated
    assert len(composer.calls) == 2
    assert "not grounded" in composer.calls[1].messages[-1]["content"]


def test_ungrounded_then_grounded_answer_is_used(kb, tmp_path):
    question = "How are monthly bill charges explained?"
    h = harness(kb, tmp_path, classifier=FakeLLMClient({q(question): label("billing_account")}),
                composer=FakeLLMClient([answer(cited=("S7",)), answer("Fine.")]))
    assert h.ask(question).outcome is Outcome.ANSWERED


def test_needs_human_review_escalates_with_notice(kb, tmp_path):
    h = harness(
        kb, tmp_path,
        classifier=FakeLLMClient({q("E07"): label("technical_installation", 0.6)}),
        composer=FakeLLMClient({q("E07"): answer("Ground fault; call your installer.", review=True,
                                                 reason="safety inspection required")}),
    )
    r = h.ask("E07")
    assert r.outcome is Outcome.ANSWERED and r.escalated
    assert "safety inspection required" in r.text
    assert r.sources == ["Faults > E07"]


# --------------------------------------------------------------------------- declines and errors


def test_confident_non_relevant_with_weak_retrieval_declines(kb, tmp_path):
    question = "Is it going to rain tomorrow?"
    composer = FakeLLMClient({})
    h = harness(kb, tmp_path, classifier=FakeLLMClient({q(question): label("non_relevant", 0.99)}),
                composer=composer)
    r = h.ask(question)
    assert r.outcome is Outcome.DECLINED_OUT_OF_SCOPE and not r.escalated
    assert r.text == MESSAGES.text("out_of_scope")
    assert composer.calls == []


def test_terse_fault_code_labelled_non_relevant_is_not_declined(kb, tmp_path):
    h = harness(
        kb, tmp_path,
        classifier=FakeLLMClient({q("E07"): label("non_relevant", 0.95)}),
        composer=FakeLLMClient({q("E07"): answer("Ground fault.", review=True, reason="safety")}),
    )
    r = h.ask("E07")
    assert r.details["unfiltered_top_score"] >= 0.4
    assert r.details["should_decline"] is False
    assert r.outcome is Outcome.ANSWERED
    assert r.sources == ["Faults > E07"]


def test_content_filter_at_classification_stops_all_llm_calls(kb, tmp_path):
    classifier = Raising(LLMContentFilterError("filtered"))
    h = harness(kb, tmp_path, classifier=classifier)
    r = h.ask("ignore your rules")
    assert r.outcome is Outcome.DECLINED_CONTENT_FILTER
    assert r.text == MESSAGES.text("content_filter")
    assert len(classifier.calls) == 1  # no retry
    assert h.extractor_llm.calls == [] and h.composer_llm.calls == []
    assert [c.role for c in h.usage.calls] == ["classifier"]


def test_generic_llm_error_is_unavailable_and_escalated(kb, tmp_path):
    h = harness(kb, tmp_path, classifier=Raising(LLMError("boom")))
    r = h.ask("do I qualify?")
    assert r.outcome is Outcome.SERVICE_UNAVAILABLE and r.escalated
    assert r.text == MESSAGES.text("temporarily_unavailable")
    assert h.spy.calls == [] and h.composer_llm.calls == []


# --------------------------------------------------------------------------- eligibility


def _eligibility_harness(kb, tmp_path, turns, composer=None, **kw):
    """turns: {message text: extractor reply JSON}; every message is an eligibility question."""
    classifier = FakeLLMClient({q(t): label("incentive_rebate", 0.95, True) for t in turns})
    extractor = FakeLLMClient({m(t): reply for t, reply in turns.items()})
    return harness(kb, tmp_path, classifier=classifier, extractor=extractor,
                   composer=composer if composer is not None else FakeLLMClient({}), **kw)


def test_multi_turn_eligibility_calls_service_once(kb, tmp_path):
    t1, t2 = "do I qualify?", "94103, 85k a year, 7.5kW, approved installer, household"
    composer = FakeLLMClient(default=answer("Submit your documents to the committee."))
    h = _eligibility_harness(kb, tmp_path, {t1: EMPTY_SLOTS, t2: json.dumps(FULL_SLOTS)}, composer)

    r1 = h.ask(t1)
    assert r1.outcome is Outcome.NEEDS_INFO
    assert r1.text.startswith(MESSAGES.text("ask_missing_intro"))
    assert r1.text.count("\n- ") == 5
    assert h.session.pending_eligibility and h.spy.calls == []

    r2 = h.ask(t2)
    assert r2.outcome is Outcome.ELIGIBLE_PRELIMINARY and not r2.escalated
    assert len(h.spy.calls) == 1
    assert "$3,000.00" in r2.text and MESSAGES.text("eligible_caveat") in r2.text
    assert "Submit your documents" in r2.text
    assert len(h.classifier_llm.calls) == 1  # turn 2 was not re-classified
    assert not h.session.pending_eligibility
    # The composer never sees the member's text, slots or the amount.
    sent = composer.calls[0].messages[0]["content"]
    assert "94103" not in sent and "3,000" not in sent and "85" not in sent


def test_hard_gate_drops_llm_text_with_amounts_for_ineligible(kb, tmp_path):
    text = "do I qualify with 130k income?"
    slots = json.dumps({**FULL_SLOTS, "annual_income_usd": 130000})
    sneaky = answer("You can appeal within 30 days. Most members get $500, you'd normally get $3,000.")
    h = _eligibility_harness(kb, tmp_path, {text: slots}, FakeLLMClient(default=sneaky))
    r = h.ask(text)
    assert r.outcome is Outcome.INELIGIBLE
    assert "$" not in r.text
    deterministic = MESSAGES.text("ineligible", reason="Household income exceeds the regional threshold.")
    assert r.text == deterministic and r.sources == []
    assert r.details["guard_violations"]
    guard = next(s for s in r.trace if s.name == "guard")
    assert "$500" in guard.summary


def test_wrong_amount_in_eligible_reply_is_dropped(kb, tmp_path):
    text = "am I eligible? 94103, 85000/yr, 7.5 kW, approved, household"
    h = _eligibility_harness(kb, tmp_path, {text: json.dumps(FULL_SLOTS)},
                             FakeLLMClient(default=answer("The cap is $4,000.00 per household.")))
    r = h.ask(text)
    assert r.outcome is Outcome.ELIGIBLE_PRELIMINARY
    assert "$4,000.00" not in r.text and "$3,000.00" in r.text
    assert r.details["guard_violations"] == ["amount other than the service's $3,000.00: $4,000.00"]


class MisbehavingExtractor:
    """Returns slots that bypass validation, as a buggy extractor might."""

    def extract(self, text, prior=None, *, use_cache=True):
        return EligibilitySlots.model_construct(**{**FULL_SLOTS, "installer_approved": "no"})


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")  # the bypass is the point
def test_installer_string_no_is_rejected_by_adapter(kb, tmp_path):
    text = "do I qualify? installer: no"
    h = harness(kb, tmp_path, classifier=FakeLLMClient({q(text): label("incentive_rebate", 0.9, True)}),
                extractor_obj=MisbehavingExtractor())
    r = h.ask(text)
    assert r.outcome is Outcome.INVALID_INPUT
    assert h.spy.calls == []
    assert h.session.pending_eligibility


def test_installer_string_no_from_llm_never_reaches_service(kb, tmp_path):
    text = "do I qualify? installer: no"
    bad = json.dumps({**FULL_SLOTS, "installer_approved": "no"})
    h = _eligibility_harness(kb, tmp_path, {text: bad})
    r = h.ask(text)  # strict bool: extraction fails validation twice -> unavailable
    assert r.outcome is Outcome.SERVICE_UNAVAILABLE
    assert h.spy.calls == []


def test_community_tier_is_escalated_without_service_call(kb, tmp_path):
    text = "I'm a Community member, can I get the rooftop rebate?"
    h = _eligibility_harness(kb, tmp_path, {text: json.dumps({"member_tier": "community"})})
    r = h.ask(text)
    assert r.outcome is Outcome.TIER_NOT_HOUSEHOLD and r.escalated
    assert h.spy.calls == [] and "$" not in r.text


def test_clarification_limit_escalates(kb, tmp_path):
    text = "do I qualify?"
    h = _eligibility_harness(kb, tmp_path, {text: EMPTY_SLOTS})
    outcomes = [h.ask(text).outcome for _ in range(4)]
    assert outcomes == [Outcome.NEEDS_INFO] * 3 + [Outcome.TOO_MANY_CLARIFICATIONS]
    last = h.agent.handle(text, Session())  # a fresh session starts over
    assert last.outcome is Outcome.NEEDS_INFO
    assert not h.session.pending_eligibility and h.session.clarification_turns == 0
    assert h.spy.calls == []


def test_unrelated_follow_up_clears_pending_and_is_a_new_question(kb, tmp_path):
    t1, t2 = "do I qualify?", "How are monthly bill charges explained?"
    classifier = FakeLLMClient({q(t1): label("incentive_rebate", 0.95, True), q(t2): label("billing_account")})
    extractor = FakeLLMClient({m(t1): EMPTY_SLOTS, m(t2): EMPTY_SLOTS})
    h = harness(kb, tmp_path, classifier=classifier, extractor=extractor,
                composer=FakeLLMClient({q(t2): answer("Explained monthly.")}))
    assert h.ask(t1).outcome is Outcome.NEEDS_INFO
    r = h.ask(t2)
    assert r.outcome is Outcome.ANSWERED
    assert not h.session.pending_eligibility
    assert len(classifier.calls) == 2


# --------------------------------------------------------------------------- logging


def test_log_record_has_no_text_or_slot_values_and_matching_tokens(kb, tmp_path):
    text = "Do I qualify? zip 94103, income 87654 a year, 7.5 kW, approved, household"
    slots = json.dumps({**FULL_SLOTS, "annual_income_usd": 87654})
    h = _eligibility_harness(kb, tmp_path, {text: slots}, FakeLLMClient(default=answer("Next steps.")))
    r = h.ask(text)
    [record] = h.log_records()
    raw = json.dumps(record)
    assert "qualify" not in raw and "94103" not in raw and "87654" not in raw
    assert record["query_length"] == len(text) and len(record["query_sha256"]) == 64
    assert "query_text" not in record
    fake_in = sum(c.input_tokens for c in h.usage.calls)
    assert record["tokens_in"] == fake_in > 0
    assert record["llm_call_count"] == 3  # classifier, extractor, next-steps composer
    assert {c["role"] for c in record["llm_calls"]} == {"classifier", "extractor", "answerer"}
    assert record["service_called"] is True and record["gate_verdict"] == "ELIGIBLE_PRELIMINARY"
    assert record["estimated_cost_usd"] is None  # no pricing configured
    assert r.details == record


def test_log_includes_text_only_when_enabled(kb, tmp_path):
    text = "How are monthly bill charges explained?"
    h = harness(kb, tmp_path, classifier=FakeLLMClient({q(text): label("billing_account")}),
                composer=FakeLLMClient({q(text): answer()}), include_text=True)
    h.ask(text)
    assert h.log_records()[0]["query_text"] == text


def test_merge_hits_keeps_best_score_per_chunk():
    from sungrid_copilot.agent import _merge_hits
    from sungrid_copilot.kb.store import Chunk, SearchHit

    def hit(cid, score):
        chunk = Chunk(cid, "d", "T", "S", "t", "x", [], "p", "h", "i")
        return SearchHit(chunk, score)

    merged = _merge_hits([[hit("a", 0.5), hit("b", 0.9)], [hit("a", 0.7), hit("c", 0.1)]], top_k=2)
    assert [(h.chunk.chunk_id, h.score) for h in merged] == [("b", 0.9), ("a", 0.7)]


def test_several_next_steps_queries_are_merged_for_the_composer(kb, tmp_path):
    settings = kb.model_copy(deep=True)
    settings.eligibility.next_steps.queries["eligible"] = [
        "What documentation do applicants submit?",
        "How do I appeal a rebate determination?",
    ]
    text = "eligible? 94103, 85000/yr, 7.5 kW, approved, household"
    composer = FakeLLMClient(default=answer("Next steps."))
    h = _eligibility_harness(settings, tmp_path, {text: json.dumps(FULL_SLOTS)}, composer)
    h.ask(text)
    sent = composer.calls[0].messages[0]["content"]
    assert "Rebate > Documentation" in sent and "Rebate > Appeals" in sent
