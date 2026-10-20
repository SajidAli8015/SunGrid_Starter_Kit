"""Retrieval orchestration: the category is a filter with a margin-based fallback, not a router.

Vector search is local and cheap, so both the unfiltered and (if in scope) the filtered search
always run. The filtered results are used only when the classifier is confident and the filter
does not cost much similarity versus searching everything.
"""

from __future__ import annotations

from dataclasses import dataclass

from sungrid_copilot.categories import NON_RELEVANT, CategorySet, load_categories
from sungrid_copilot.classify import ClassificationResult
from sungrid_copilot.config import RetrievalSettings, Settings
from sungrid_copilot.kb.embeddings import Embedder, get_embedder
from sungrid_copilot.kb.store import ChromaVectorStore, SearchHit, VectorStore

LOW_CLASSIFIER_CONFIDENCE = "low_classifier_confidence"
NON_RELEVANT_UNCERTAIN = "non_relevant_uncertain"
UNFILTERED_CLEARLY_BETTER = "unfiltered_clearly_better"


@dataclass(frozen=True)
class RetrievalResult:
    hits: list[SearchHit]  # the chunks to use
    filter_used: str | None  # category, or None when unfiltered results were used
    fallback_reason: str | None  # why unfiltered was used, None if the filter was used
    filtered_top_score: float | None
    unfiltered_top_score: float | None
    margin: float | None  # unfiltered top-1 minus filtered top-1


class Retriever:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        categories: CategorySet,
        settings: RetrievalSettings,
    ):
        self.store = store
        self.embedder = embedder
        self.categories = categories
        self.settings = settings
        self._embeddings: dict[str, list[float]] = {}  # calibration re-runs the same queries

    @classmethod
    def from_settings(cls, settings: Settings, embedder: Embedder | None = None) -> Retriever:
        model_name = embedder.model_name if embedder else settings.embedding.model
        # Open (and check the model) before loading the embedder, so a stale index fails fast.
        store = ChromaVectorStore.open(
            settings.vector_store.resolved_path, settings.vector_store.collection, model_name
        )
        return cls(
            store,
            embedder or get_embedder(model_name),
            load_categories(settings.categories.resolved_file),
            settings.retrieval,
        )

    def with_settings(self, settings: RetrievalSettings) -> Retriever:
        """A copy with other thresholds, sharing the store and query-embedding cache."""
        clone = Retriever(self.store, self.embedder, self.categories, settings)
        clone._embeddings = self._embeddings
        return clone

    def retrieve(
        self,
        query: str,
        classification: ClassificationResult,
        *,
        force_category: str | None = None,
        fallback: bool = True,
        top_k: int | None = None,
    ) -> RetrievalResult:
        """`force_category` overrides the classifier's label (diagnostics and calibration).
        `fallback=False` disables only the margin rule; it exists for the calibration experiment."""
        if force_category is not None:
            self.categories.require(force_category)
        category = force_category or classification.category
        in_scope = category in self.categories.names
        k = top_k or self.settings.top_k

        embedding = self._embed(query)
        unfiltered = self.store.query(embedding, k)
        filtered = self.store.query(embedding, k, category=category) if in_scope else []
        unfiltered_top = unfiltered[0].score if unfiltered else None
        filtered_top = filtered[0].score if filtered else None
        margin = (
            unfiltered_top - filtered_top
            if unfiltered_top is not None and filtered_top is not None
            else None
        )

        if not in_scope:
            reason = NON_RELEVANT_UNCERTAIN  # caller decides on a decline via should_decline
        elif classification.confidence < self.settings.classifier_min_conf:
            reason = LOW_CLASSIFIER_CONFIDENCE
        elif fallback and (margin is None or margin > self.settings.fallback_margin):
            reason = UNFILTERED_CLEARLY_BETTER
        else:
            reason = None

        return RetrievalResult(
            hits=unfiltered if reason else filtered,
            filter_used=None if reason else category,
            fallback_reason=reason,
            filtered_top_score=filtered_top,
            unfiltered_top_score=unfiltered_top,
            margin=margin,
        )

    def should_decline(
        self, classification: ClassificationResult, result: RetrievalResult
    ) -> bool:
        """The only early exit: a confident non_relevant label AND weak unfiltered retrieval."""
        top = result.unfiltered_top_score if result.unfiltered_top_score is not None else 0.0
        return (
            classification.category == NON_RELEVANT
            and classification.confidence >= self.settings.non_relevant_min_conf
            and top < self.settings.non_relevant_score_ceiling
        )

    def _embed(self, query: str) -> list[float]:
        if query not in self._embeddings:
            self._embeddings[query] = self.embedder.embed_query(query)
        return self._embeddings[query]
