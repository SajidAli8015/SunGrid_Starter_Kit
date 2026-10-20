"""Ingestion: manifest -> `##` chunks -> embeddings -> rebuilt vector store."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sungrid_copilot.categories import load_categories
from sungrid_copilot.config import PROJECT_ROOT, Settings
from sungrid_copilot.kb.chunking import split_sections
from sungrid_copilot.kb.embeddings import Embedder
from sungrid_copilot.kb.manifest import DocEntry, load_manifest
from sungrid_copilot.kb.store import Chunk, ChromaVectorStore


def build_chunks(
    entries: list[DocEntry], docs_dir: Path, max_tokens: int, *, ingested_at: str | None = None
) -> list[Chunk]:
    ingested_at = ingested_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    chunks: list[Chunk] = []
    for entry in entries:
        path = docs_dir / entry.file
        markdown = path.read_text(encoding="utf-8")
        for i, section in enumerate(split_sections(markdown, max_tokens)):
            chunks.append(
                Chunk(
                    chunk_id=f"{entry.doc_id}::{i:02d}",
                    doc_id=entry.doc_id,
                    title=entry.title,
                    section=section.heading,
                    text=section.body,
                    primary=entry.primary,
                    secondary=list(entry.secondary),
                    source_path=_display_path(path),
                    content_hash=hashlib.sha256(section.body.encode("utf-8")).hexdigest()[:16],
                    ingested_at=ingested_at,
                )
            )
    return chunks


def ingest(settings: Settings, embedder: Embedder) -> dict[str, int]:
    """Drop and rebuild the collection. Returns chunk counts per doc_id, in manifest order."""
    entries = load_manifest(
        settings.ingestion.resolved_manifest,
        settings.ingestion.resolved_docs_dir,
        load_categories(settings.categories.resolved_file),
    )
    chunks = build_chunks(
        entries, settings.ingestion.resolved_docs_dir, settings.ingestion.max_chunk_tokens
    )
    embeddings = embedder.embed_documents([c.embedding_text for c in chunks])
    store = ChromaVectorStore.rebuild(
        settings.vector_store.resolved_path, settings.vector_store.collection, embedder.model_name
    )
    store.add(chunks, embeddings)

    counts = {e.doc_id: 0 for e in entries}
    for chunk in chunks:
        counts[chunk.doc_id] += 1
    return counts


def _display_path(path: Path) -> str:
    """Repo-relative POSIX path when possible, so metadata is the same on Windows and Linux."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
