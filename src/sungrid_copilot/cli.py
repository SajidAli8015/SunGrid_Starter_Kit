"""Command-line entry point: `python -m sungrid_copilot.cli <command>`."""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import BaseModel

from sungrid_copilot.categories import DOC_CATEGORIES, Category
from sungrid_copilot.config import ConfigError, load_settings
from sungrid_copilot.kb.embeddings import EmbeddingError, get_embedder
from sungrid_copilot.kb.ingest import ingest
from sungrid_copilot.kb.manifest import ManifestError
from sungrid_copilot.kb.search import search
from sungrid_copilot.kb.store import IndexNotReadyError
from sungrid_copilot.llm import LLMError, get_llm_client
from sungrid_copilot.llm.factory import describe_provider

SNIPPET_CHARS = 120


class _Ping(BaseModel):
    status: str


def check_llm() -> int:
    """Print the provider setup, then make one plain and one JSON call."""
    try:
        settings = load_settings()
        for label, value in describe_provider(settings).items():
            print(f"{label}: {value}")

        client = get_llm_client(settings=settings)
        reply = client.complete(
            "You are a connectivity check.",
            [{"role": "user", "content": "Reply with the single word: pong"}],
            max_tokens=10,
        )
        print(f"\nReply: {reply.text.strip()!r}")
        print(f"Model: {reply.model}")
        print(f"Tokens: {reply.input_tokens} in / {reply.output_tokens} out")
        print(f"Latency: {reply.latency_s:.2f}s")

        parsed = client.complete_json(
            "You are a connectivity check.",
            [{"role": "user", "content": 'Return a JSON object with "status" set to "ok".'}],
            _Ping,
            max_tokens=50,
        )
        print(f"\nJSON: {parsed.value.model_dump()} ({len(parsed.responses)} attempt(s))")
    except (ConfigError, LLMError) as e:
        print(f"\ncheck-llm failed: {e}", file=sys.stderr)
        return 1
    print("\ncheck-llm OK")
    return 0


def run_ingest() -> int:
    """Rebuild the vector index from docs/ and the manifest."""
    try:
        settings = load_settings()
        counts = ingest(settings, get_embedder(settings.embedding.model))
    except (ConfigError, ManifestError, EmbeddingError) as e:
        print(f"ingest failed: {e}", file=sys.stderr)
        return 1
    width = max(len(doc_id) for doc_id in counts)
    for doc_id, n in counts.items():
        print(f"{doc_id:<{width}}  {n:>3} chunks")
    print(f"Total: {sum(counts.values())} chunks from {len(counts)} docs "
          f"(embedding model: {settings.embedding.model})")
    return 0


def run_search(query: str, category: str | None, top_k: int | None, as_json: bool) -> int:
    """Print raw retrieval results. No LLM call."""
    try:
        settings = load_settings()
        hits = search(
            settings, query, top_k=top_k, category=Category(category) if category else None
        )
    except (ConfigError, IndexNotReadyError, EmbeddingError) as e:
        print(f"search failed: {e}", file=sys.stderr)
        return 1

    if as_json:
        rows = [
            {
                "rank": rank,
                "score": round(hit.score, 4),
                "chunk_id": hit.chunk.chunk_id,
                "title": hit.chunk.title,
                "section": hit.chunk.section,
                "primary": hit.chunk.primary,
                "secondary": hit.chunk.secondary,
                "source_path": hit.chunk.source_path,
                "text": hit.chunk.text,
            }
            for rank, hit in enumerate(hits, 1)
        ]
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    if not hits:
        print("No results.")
    for rank, hit in enumerate(hits, 1):
        snippet = " ".join(hit.chunk.text.split())[:SNIPPET_CHARS]
        print(f"{rank}. [{hit.score:.3f}] {hit.chunk.title} > {hit.chunk.section}")
        print(f"   {snippet}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Piped output on Windows defaults to the locale code page; always emit UTF-8 instead.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="sungrid_copilot.cli", description="SunGrid Copilot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-llm", help="Smoke-test the configured LLM provider")
    sub.add_parser("ingest", help="Rebuild the vector index from docs/")
    search_parser = sub.add_parser("search", help="Raw vector search (no LLM)")
    search_parser.add_argument("query")
    search_parser.add_argument("--category", choices=[c.value for c in DOC_CATEGORIES])
    search_parser.add_argument("--top-k", type=int, default=None)
    search_parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)
    if getattr(args, "top_k", None) is not None and args.top_k < 1:
        parser.error("--top-k must be at least 1")

    if args.command == "check-llm":
        return check_llm()
    if args.command == "ingest":
        return run_ingest()
    if args.command == "search":
        return run_search(args.query, args.category, args.top_k, args.json)
    return 2


if __name__ == "__main__":
    sys.exit(main())
