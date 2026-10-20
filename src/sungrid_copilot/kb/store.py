"""Vector store interface and its Chroma implementation.

Chroma cannot filter on list values, so each chunk also gets one boolean `cat_<category>` flag
per category in primary + secondary. That detail stays inside this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

_INGEST_HINT = "Run `python -m sungrid_copilot.cli ingest` to rebuild the index."


class IndexNotReadyError(Exception):
    """The index is missing or was built with a different embedding model."""


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str  # plain section body, for display and for the answer prompt
    primary: str
    secondary: list[str]
    source_path: str
    content_hash: str
    ingested_at: str

    @property
    def embedding_text(self) -> str:
        # Headings such as "Eligibility" repeat across docs, so the title disambiguates.
        return f"{self.title} > {self.section}\n{self.text}"

    @property
    def categories(self) -> list[str]:
        return [self.primary, *self.secondary]


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float  # cosine similarity, 1 - distance


class VectorStore(ABC):
    @abstractmethod
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        ...

    @abstractmethod
    def query(
        self, embedding: list[float], top_k: int, category: str | None = None
    ) -> list[SearchHit]:
        """Top-k by similarity. With a category, only chunks whose primary OR secondary matches."""

    @abstractmethod
    def count(self) -> int:
        ...


class ChromaVectorStore(VectorStore):
    def __init__(self, collection):
        self._collection = collection

    @classmethod
    def rebuild(cls, path: Path, name: str, embedding_model: str) -> ChromaVectorStore:
        """Drop any existing collection and create an empty one tagged with the model name."""
        client = _client(path)
        if name in _collection_names(client):
            client.delete_collection(name)
        collection = client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine", "embedding_model": embedding_model},
            embedding_function=None,  # we always pass our own embeddings
        )
        return cls(collection)

    @classmethod
    def open(cls, path: Path, name: str, embedding_model: str) -> ChromaVectorStore:
        """Open an existing index, failing loudly if it is missing or uses another model."""
        client = _client(path) if path.exists() else None
        if client is None or name not in _collection_names(client):
            raise IndexNotReadyError(f"No index found at {path}. {_INGEST_HINT}")
        collection = client.get_collection(name=name, embedding_function=None)
        indexed_model = (collection.metadata or {}).get("embedding_model")
        if indexed_model != embedding_model:
            raise IndexNotReadyError(
                f"Index was built with embedding model '{indexed_model}' but config uses "
                f"'{embedding_model}'. {_INGEST_HINT}"
            )
        return cls(collection)

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if not chunks:
            return
        self._collection.add(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[_to_metadata(c) for c in chunks],
        )

    def query(
        self, embedding: list[float], top_k: int, category: str | None = None
    ) -> list[SearchHit]:
        total = self.count()
        if total == 0:
            return []
        where = {f"cat_{category}": True} if category else None
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, total),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return [
            SearchHit(chunk=_from_metadata(chunk_id, doc, meta), score=1.0 - distance)
            for chunk_id, doc, meta, distance in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
            )
        ]

    def count(self) -> int:
        return self._collection.count()


def _client(path: Path):
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.PersistentClient(
        path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
    )


def _collection_names(client) -> set[str]:
    # Chroma has returned both names and Collection objects here across versions.
    return {getattr(c, "name", c) for c in client.list_collections()}


def _to_metadata(chunk: Chunk) -> dict:
    metadata = {
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "section": chunk.section,
        "primary": chunk.primary,
        "secondary": ",".join(chunk.secondary),  # lists are not filterable; flags below are
        "source_path": chunk.source_path,
        "content_hash": chunk.content_hash,
        "ingested_at": chunk.ingested_at,
    }
    metadata.update({f"cat_{category}": True for category in chunk.categories})
    return metadata


def _from_metadata(chunk_id: str, text: str, meta: dict) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=meta["doc_id"],
        title=meta["title"],
        section=meta["section"],
        text=text,
        primary=meta["primary"],
        secondary=[s for s in meta["secondary"].split(",") if s],
        source_path=meta["source_path"],
        content_hash=meta["content_hash"],
        ingested_at=meta["ingested_at"],
    )
