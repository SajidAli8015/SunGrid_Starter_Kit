"""Shared fixtures for offline agent tests: fake LLM scripts, a tiny KB, a spy on the real stub."""

import json

import stub_tools

from kb_helpers import entry, write_kb
from sungrid_copilot.agent import CopilotAgent, Session
from sungrid_copilot.answer import AnswerComposer
from sungrid_copilot.categories import load_categories
from sungrid_copilot.classify import Classifier
from sungrid_copilot.config import Settings, load_settings
from sungrid_copilot.eligibility.adapter import EligibilityAdapter
from sungrid_copilot.eligibility.slots import SlotExtractor
from sungrid_copilot.kb.embeddings import HashEmbedder
from sungrid_copilot.kb.ingest import ingest
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


def build_kb(root):
    """Temp KB (hash embedder) and settings shared by the agent and eval tests."""
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
