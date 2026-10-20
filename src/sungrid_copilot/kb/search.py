"""Raw vector search over the ingested knowledge base (no LLM involved)."""

from __future__ import annotations

from sungrid_copilot.categories import Category
from sungrid_copilot.config import Settings
from sungrid_copilot.kb.embeddings import Embedder, get_embedder
from sungrid_copilot.kb.store import ChromaVectorStore, SearchHit


def search(
    settings: Settings,
    query: str,
    *,
    top_k: int | None = None,
    category: Category | None = None,
    embedder: Embedder | None = None,
) -> list[SearchHit]:
    model_name = embedder.model_name if embedder else settings.embedding.model
    # Open (and check the model) before loading the embedder, so a stale index fails fast.
    store = ChromaVectorStore.open(
        settings.vector_store.resolved_path, settings.vector_store.collection, model_name
    )
    embedder = embedder or get_embedder(model_name)
    return store.query(
        embedder.embed_query(query), top_k or settings.retrieval.top_k, category=category
    )
