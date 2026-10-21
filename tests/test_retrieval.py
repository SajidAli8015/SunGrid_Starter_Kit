import pytest

from sungrid_copilot.categories import NON_RELEVANT, CategoryError, load_categories
from sungrid_copilot.classify import ClassificationResult
from sungrid_copilot.config import RetrievalSettings, load_settings
from sungrid_copilot.kb.embeddings import HashEmbedder
from sungrid_copilot.kb.store import Chunk, SearchHit, VectorStore
from sungrid_copilot.retrieval import (
    LOW_CLASSIFIER_CONFIDENCE,
    NON_RELEVANT_UNCERTAIN,
    UNFILTERED_CLEARLY_BETTER,
    Retriever,
)

CATEGORIES = load_categories(load_settings().categories.resolved_file)
SETTINGS = RetrievalSettings(
    top_k=3,
    classifier_min_conf=0.6,
    non_relevant_min_conf=0.85,
    fallback_margin=0.05,
    non_relevant_score_ceiling=0.60,
)


def _hit(doc_id: str, score: float) -> SearchHit:
    chunk = Chunk(
        chunk_id=f"{doc_id}::00",
        doc_id=doc_id,
        title=doc_id,
        section="S",
        text="t",
        primary="x",
        secondary=[],
        source_path=f"docs/{doc_id}.md",
        content_hash="h",
        ingested_at="t",
    )
    return SearchHit(chunk=chunk, score=score)


class FakeStore(VectorStore):
    """Scripted results per category (None = unfiltered); records the queries it gets."""

    def __init__(self, results: dict[str | None, list[SearchHit]]):
        self.results = results
        self.calls: list[str | None] = []

    def add(self, chunks, embeddings):
        raise NotImplementedError

    def query(self, embedding, top_k, category=None):
        self.calls.append(category)
        return self.results.get(category, [])[:top_k]

    def count(self):
        return sum(len(v) for v in self.results.values())


def _label(category: str, confidence: float = 0.9) -> ClassificationResult:
    return ClassificationResult(
        category=category, confidence=confidence, needs_eligibility_check=False, rationale="t"
    )


def _retriever(results, settings=SETTINGS) -> Retriever:
    return Retriever(FakeStore(results), HashEmbedder(), CATEGORIES, settings)


def test_correct_category_close_margin_uses_filter():
    r = _retriever(
        {None: [_hit("other", 0.82), _hit("bills", 0.80)], "billing_account": [_hit("bills", 0.80)]}
    )
    result = r.retrieve("q", _label("billing_account"))
    assert result.filter_used == "billing_account"
    assert result.fallback_reason is None
    assert [h.chunk.doc_id for h in result.hits] == ["bills"]
    assert result.margin == pytest.approx(0.02)
    assert r.store.calls == [None, "billing_account"]  # both searches always run


def test_wrong_category_falls_back_when_unfiltered_clearly_better():
    r = _retriever({None: [_hit("appeals", 0.89)], "program_policies": [_hit("grievance", 0.75)]})
    result = r.retrieve("q", _label("program_policies"))
    assert result.filter_used is None
    assert result.fallback_reason == UNFILTERED_CLEARLY_BETTER
    assert result.hits[0].chunk.doc_id == "appeals"
    assert result.margin == pytest.approx(0.14)


def test_empty_filtered_results_fall_back():
    r = _retriever({None: [_hit("a", 0.7)]})
    result = r.retrieve("q", _label("company_updates"))
    assert result.fallback_reason == UNFILTERED_CLEARLY_BETTER
    assert result.filtered_top_score is None and result.margin is None


def test_low_confidence_searches_unfiltered():
    r = _retriever({None: [_hit("a", 0.8)], "billing_account": [_hit("a", 0.8)]})
    result = r.retrieve("q", _label("billing_account", confidence=0.4))
    assert result.fallback_reason == LOW_CLASSIFIER_CONFIDENCE
    assert result.filter_used is None


def test_fallback_disabled_keeps_filter():
    r = _retriever({None: [_hit("appeals", 0.89)], "program_policies": [_hit("grievance", 0.75)]})
    result = r.retrieve("q", _label("program_policies"), fallback=False)
    assert result.filter_used == "program_policies"
    assert result.fallback_reason is None
    assert result.hits[0].chunk.doc_id == "grievance"


def test_non_relevant_label_searches_unfiltered_only():
    r = _retriever({None: [_hit("faults", 0.7)]})
    result = r.retrieve("E07", _label(NON_RELEVANT, 0.95))
    assert result.fallback_reason == NON_RELEVANT_UNCERTAIN
    assert result.hits[0].chunk.doc_id == "faults"
    assert r.store.calls == [None]


def test_force_category_overrides_label_and_is_validated():
    r = _retriever({None: [_hit("a", 0.8)], "company_updates": [_hit("news", 0.79)]})
    result = r.retrieve("q", _label("billing_account"), force_category="company_updates")
    assert result.filter_used == "company_updates"
    with pytest.raises(CategoryError):
        r.retrieve("q", _label("billing_account"), force_category="nope")


def test_with_settings_changes_margin():
    r = _retriever({None: [_hit("a", 0.80)], "billing_account": [_hit("b", 0.72)]})
    assert r.retrieve("q", _label("billing_account")).fallback_reason == UNFILTERED_CLEARLY_BETTER
    wide = r.with_settings(SETTINGS.model_copy(update={"fallback_margin": 0.10}))
    assert wide.retrieve("q", _label("billing_account")).filter_used == "billing_account"


@pytest.mark.parametrize(
    "label, unfiltered_top, expected",
    [
        (_label(NON_RELEVANT, 0.95), 0.45, True),  # all three conditions hold
        (_label(NON_RELEVANT, 0.95), 0.72, False),  # "E07": confident label, strong retrieval
        (_label(NON_RELEVANT, 0.70), 0.45, False),  # low confidence
        (_label("billing_account", 0.95), 0.45, False),  # not non_relevant
        (_label(NON_RELEVANT, 0.85), 0.5999, True),  # boundaries: >= conf, < ceiling
        (_label(NON_RELEVANT, 0.95), 0.60, False),
    ],
)
def test_should_decline_needs_both_signals(label, unfiltered_top, expected):
    r = _retriever({None: [_hit("a", unfiltered_top)]})
    assert r.should_decline(label, r.retrieve("q", label)) is expected


def test_query_embedding_cache_is_a_bounded_lru():
    """Member queries must not pile up in memory for the life of the agent (F8)."""
    from sungrid_copilot.retrieval import EMBEDDING_CACHE_SIZE

    r = _retriever({None: [_hit("a", 0.8)]})
    assert 100 <= EMBEDDING_CACHE_SIZE <= 1000
    for i in range(EMBEDDING_CACHE_SIZE + 50):
        r.retrieve(f"query {i}", _label("billing_account"))
    assert len(r._embeddings) == EMBEDDING_CACHE_SIZE
    assert "query 0" not in r._embeddings and f"query {EMBEDDING_CACHE_SIZE + 49}" in r._embeddings

    oldest = next(iter(r._embeddings))
    r.retrieve(oldest, _label("billing_account"))  # a hit refreshes the entry
    r.retrieve("one more", _label("billing_account"))
    assert oldest in r._embeddings and len(r._embeddings) == EMBEDDING_CACHE_SIZE
