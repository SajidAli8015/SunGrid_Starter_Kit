"""Command-line entry point: `python -m sungrid_copilot.cli <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from sungrid_copilot.agent import AgentResponse, CopilotAgent, Session
from sungrid_copilot.calibrate import format_summary, load_dev_set, run_calibration, save_report
from sungrid_copilot.categories import CategoryError, load_categories
from sungrid_copilot.classify import Classifier
from sungrid_copilot.config import PROJECT_ROOT, ConfigError, load_settings
from sungrid_copilot.eligibility.adapter import EligibilityAdapter
from sungrid_copilot.eligibility.flow import run_eligibility
from sungrid_copilot.eligibility.guard import check_final_text
from sungrid_copilot.eligibility.render import load_messages, render
from sungrid_copilot.eligibility.slots import EligibilitySlots, SlotExtractor
from sungrid_copilot.kb.embeddings import EmbeddingError, get_embedder
from sungrid_copilot.kb.ingest import ingest
from sungrid_copilot.kb.manifest import ManifestError, load_manifest
from sungrid_copilot.kb.search import search
from sungrid_copilot.kb.store import IndexNotReadyError
from sungrid_copilot.llm import LLMError, get_llm_client
from sungrid_copilot.llm.factory import describe_provider
from sungrid_copilot.messages import Messages, MessagesError
from sungrid_copilot.retrieval import Retriever
from sungrid_copilot.usage import find_price

SNIPPET_CHARS = 120
DEFAULT_DEV_SET = PROJECT_ROOT / "eval" / "dev_queries.yaml"
CALIBRATION_REPORT = PROJECT_ROOT / "eval" / "results" / "calibration.json"
_ERRORS = (ConfigError, CategoryError, ManifestError, IndexNotReadyError, EmbeddingError, LLMError)


def _print_eligibility(slots: EligibilitySlots, settings) -> None:
    messages = load_messages(Messages.load(settings.messages.resolved_file))
    outcome = run_eligibility(slots, EligibilityAdapter.from_settings(settings))
    text = render(outcome, messages)
    print(f"outcome:   {outcome}")
    print(f"escalate:  {outcome.escalate}")
    print(f"guard:     {check_final_text(text, outcome, messages) or 'no violations'}")
    print()
    print(text)


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
        provider = settings.llm.provider
        if find_price(provider, client.model, reply.model, settings.pricing,
                      settings.pricing_model_map) is None:
            print(
                f"Warning: no price for provider '{provider}', model '{client.model}' (reported as "
                f"'{reply.model}') in `pricing` in config/config.yaml; estimated cost will be null. "
                "Add a price, or map the deployment in `pricing_model_map`.",
                file=sys.stderr,
            )

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
    except (ConfigError, CategoryError, ManifestError, EmbeddingError) as e:
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
        if category:
            load_categories(settings.categories.resolved_file).require(category)
        hits = search(settings, query, top_k=top_k, category=category)
    except (ConfigError, CategoryError, IndexNotReadyError, EmbeddingError) as e:
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


def run_classify(query: str, use_cache: bool) -> int:
    """Classify one query and print the parsed result."""
    try:
        outcome = Classifier.from_settings(load_settings()).classify(query, use_cache=use_cache)
    except (*_ERRORS, ValueError) as e:
        print(f"classify failed: {e}", file=sys.stderr)
        return 1
    print(json.dumps(outcome.result.model_dump(), indent=2, ensure_ascii=False))
    source = "cache (no LLM call)" if outcome.cached else f"{outcome.model}, {outcome.latency_s:.2f}s"
    print(f"[{source}; tokens {outcome.input_tokens} in / {outcome.output_tokens} out]")
    return 0


def run_retrieve(query: str, force_category: str | None, top_k: int | None, use_cache: bool) -> int:
    """Classify + retrieve with diagnostics. No answer composition."""
    try:
        settings = load_settings()
        retriever = Retriever.from_settings(settings)
        if force_category:
            retriever.categories.require(force_category)
        result = Classifier.from_settings(settings).classify(query, use_cache=use_cache).result
        retrieved = retriever.retrieve(query, result, force_category=force_category, top_k=top_k)
    except (*_ERRORS, ValueError) as e:
        print(f"retrieve failed: {e}", file=sys.stderr)
        return 1

    def fmt(x: float | None) -> str:
        return "-" if x is None else f"{x:.3f}"

    print(f"category:                {result.category} (confidence {result.confidence:.2f})")
    print(f"needs_eligibility_check: {result.needs_eligibility_check}")
    print(f"rationale:               {result.rationale}")
    if force_category:
        print(f"forced category:         {force_category}")
    print(f"filter used:             {retrieved.filter_used or 'none (unfiltered)'}")
    print(f"fallback reason:         {retrieved.fallback_reason or '-'}")
    print(
        f"top-1 scores:            unfiltered {fmt(retrieved.unfiltered_top_score)}, "
        f"filtered {fmt(retrieved.filtered_top_score)}, margin {fmt(retrieved.margin)} "
        f"(fallback_margin {settings.retrieval.fallback_margin})"
    )
    print(f"should_decline:          {retriever.should_decline(result, retrieved)}")
    print()
    for rank, hit in enumerate(retrieved.hits, 1):
        print(f"{rank}. [{hit.score:.3f}] {hit.chunk.title} > {hit.chunk.section}")
    return 0


def run_calibrate(dev_set: Path, workers: int, use_cache: bool) -> int:
    """Classifier accuracy, score distributions and margin sweep on the dev set."""
    try:
        settings = load_settings()
        retriever = Retriever.from_settings(settings)
        entries = load_manifest(
            settings.ingestion.resolved_manifest,
            settings.ingestion.resolved_docs_dir,
            retriever.categories,
        )
        queries = load_dev_set(dev_set, retriever.categories, {e.doc_id for e in entries})
        report = run_calibration(
            Classifier.from_settings(settings), retriever, queries, workers=workers, use_cache=use_cache
        )
    except (*_ERRORS, ValueError, OSError) as e:
        print(f"calibrate failed: {e}", file=sys.stderr)
        return 1
    save_report(report, CALIBRATION_REPORT)
    print(format_summary(report))
    print(f"\nFull report: {CALIBRATION_REPORT.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


def run_eligibility_cli(args: argparse.Namespace) -> int:
    """Run the eligibility flow from explicit options. No LLM."""
    try:
        settings = load_settings()
        installer = None if args.installer_approved is None else args.installer_approved == "yes"
        slots = EligibilitySlots(
            household_zip=args.zip,
            annual_income_usd=args.income,
            system_size_kw=args.size_kw,
            installer_approved=installer,
            member_tier=args.tier,
        )
        _print_eligibility(slots, settings)
    except (ConfigError, MessagesError) as e:
        print(f"eligibility failed: {e}", file=sys.stderr)
        return 1
    return 0


def run_extract_slots(text: str, use_cache: bool) -> int:
    """Extract slots with the LLM (role: extractor), then show what the flow would do."""
    try:
        settings = load_settings()
        slots = SlotExtractor.from_settings(settings).extract(text, use_cache=use_cache)
        print(json.dumps(slots.model_dump(), indent=2, ensure_ascii=False))
        print(f"missing:   {slots.missing() or 'none'}\n")
        _print_eligibility(slots, settings)
    except (*_ERRORS, MessagesError) as e:
        print(f"extract-slots failed: {e}", file=sys.stderr)
        return 1
    return 0


def _print_response(response: AgentResponse, debug: bool) -> None:
    print(response.text)
    if response.escalated:
        print(f"\nFlagged for human review: {response.escalation_reason}")
    if not debug:
        return
    d = response.details
    print("\n--- debug ---")
    print(f"outcome: {response.outcome.value}")
    for step in response.trace:
        print(f"  {step.name:<15} {step.ms:>8.1f} ms  {step.summary}")
    for chunk in d.get("retrieved", []):
        print(f"  retrieved {chunk['score']:.3f}  {chunk['chunk_id']}")
    print(
        f"  service called: {d.get('service_called')}, gate verdict: {d.get('gate_verdict')}, "
        f"guard violations: {d.get('guard_violations') or 'none'}"
    )
    print(
        f"  LLM calls: {d['llm_call_count']} "
        f"({', '.join(c['role'] for c in d['llm_calls']) or 'none'}), "
        f"tokens {d['tokens_in']} in / {d['tokens_out']} out, "
        f"cost {d['estimated_cost_usd'] if d['estimated_cost_usd'] is not None else 'n/a (no pricing)'}"
    )
    print(f"  total latency: {d['latency_ms']:.0f} ms")


def run_ask(once: str | None, debug: bool) -> int:
    """Interactive Copilot session (or a single message with --once)."""
    try:
        agent = CopilotAgent.from_settings(load_settings())
    except (*_ERRORS, MessagesError) as e:
        print(f"ask failed to start: {e}", file=sys.stderr)
        return 1
    session = Session()  # in memory only
    if once is not None:
        _print_response(agent.handle(once, session), debug)
        return 0
    print("SunGrid Copilot. Type 'exit' to quit.")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in {"exit", "quit"}:
            break
        if text:
            _print_response(agent.handle(text, session), debug)
    return 0

DEFAULT_QUESTIONS = PROJECT_ROOT / "eval" / "questions.yaml"
RESULTS_DIR = PROJECT_ROOT / "eval" / "results"


def run_eval_cli(args: argparse.Namespace) -> int:
    """Run the held-out evaluation set and write results.json, summary.md and grade_sheet.csv."""
    from datetime import datetime, timezone

    from sungrid_copilot.answer import AnswerComposer
    from sungrid_copilot.evaluation.full_context import run_full_context
    from sungrid_copilot.evaluation.report import build_meta, write_outputs
    from sungrid_copilot.evaluation.runner import run_eval
    from sungrid_copilot.evaluation.schema import EvalSetError, load_eval_set
    from sungrid_copilot.kb.ingest import build_chunks
    from sungrid_copilot.usage import TrackedLLM, UsageTracker, estimate_cost

    try:
        settings = load_settings()
        categories = load_categories(settings.categories.resolved_file)
        entries = load_manifest(
            settings.ingestion.resolved_manifest, settings.ingestion.resolved_docs_dir, categories
        )
        eval_set = load_eval_set(args.questions, {e.doc_id for e in entries})
    except (*_ERRORS, EvalSetError) as e:
        print(f"eval failed: {e}", file=sys.stderr)
        return 1

    questions = eval_set.questions
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        questions = [q for q in questions if q.id in wanted]
    if args.tags:
        wanted_tags = {t.strip() for t in args.tags.split(",") if t.strip()}
        questions = [q for q in questions if wanted_tags.intersection(q.tags)]
    if not questions:
        print("eval failed: no questions match --ids/--tags", file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "-full-context" if args.mode == "full-context" else ""
    run_dir = args.out or RESULTS_DIR / f"{stamp}{suffix}"
    title_to_stem = {e.title: e.doc_id for e in entries}
    # Same member-session path as `ask` (LLM caches off), but logs go to the run folder.
    run_settings = settings.model_copy(deep=True)
    run_settings.logging.path = run_dir / "queries.jsonl"
    print(f"Running {len(questions)} question(s), mode={args.mode}, workers={args.workers}, "
          f"repeat={args.repeat} -> {run_dir}")

    if args.mode == "pipeline":
        records = run_eval(
            questions,
            lambda: CopilotAgent.from_settings(run_settings),
            title_to_stem,
            workers=args.workers,
            repeat=args.repeat,
        )
    else:
        chunks = build_chunks(
            entries, settings.ingestion.resolved_docs_dir, settings.ingestion.max_chunk_tokens
        )

        def composer_factory():
            usage = UsageTracker()
            client = TrackedLLM(get_llm_client("answerer", settings), "answerer", usage)
            return AnswerComposer.from_settings(settings, client=client), usage

        records = run_full_context(
            questions,
            composer_factory,
            chunks,
            load_messages(Messages.load(settings.messages.resolved_file)),
            title_to_stem,
            workers=args.workers,
            cost_fn=lambda calls: estimate_cost(
                calls, settings.llm.provider, settings.pricing, settings.pricing_model_map
            ),
        )

    models = sorted({c["model"] for r in records for c in r.get("llm_calls", [])})
    meta = build_meta(
        settings, args.questions, mode=args.mode, repeat=args.repeat, workers=args.workers,
        model=", ".join(models) or "unknown",
    )
    write_outputs(run_dir, meta, records, eval_set)
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    for section in ("## Automated checks", "## Failing questions"):
        part = summary.split(section, 1)[1].split("\n## ", 1)[0]
        print(f"\n{section}{part.rstrip()}")
    print(f"\nRun folder: {run_dir}")
    return 0


def run_eval_summarize(run_dir: Path, grades: Path) -> int:
    from sungrid_copilot.evaluation.report import GradeError, merge_grades

    try:
        text = merge_grades(run_dir, grades)
    except (OSError, KeyError, GradeError) as e:
        print(f"eval-summarize failed: {e}", file=sys.stderr)
        return 1
    header = "## Hand grading"
    print((header + text.split(header, 1)[1]).strip())
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
    search_parser.add_argument("--category", help="Filter to one category from config/categories.yaml")
    search_parser.add_argument("--top-k", type=int, default=None)
    search_parser.add_argument("--json", action="store_true", help="Machine-readable output")

    classify_parser = sub.add_parser("classify", help="Classify one query (1 LLM call, cached)")
    classify_parser.add_argument("query")
    classify_parser.add_argument("--no-cache", action="store_true")

    retrieve_parser = sub.add_parser("retrieve", help="Classify + retrieve with diagnostics")
    retrieve_parser.add_argument("query")
    retrieve_parser.add_argument("--force-category", help="Override the classifier's category")
    retrieve_parser.add_argument("--top-k", type=int, default=None)
    retrieve_parser.add_argument("--no-cache", action="store_true")

    calibrate_parser = sub.add_parser("calibrate", help="Tune thresholds on the dev set")
    calibrate_parser.add_argument("--dev-set", type=Path, default=DEFAULT_DEV_SET)
    calibrate_parser.add_argument("--workers", type=int, default=3)
    calibrate_parser.add_argument("--no-cache", action="store_true")

    elig_parser = sub.add_parser("eligibility", help="Rooftop Rebate flow from explicit values (no LLM)")
    elig_parser.add_argument("--zip", help="Household ZIP code")
    elig_parser.add_argument("--income", type=float, help="Annual household AGI in USD")
    elig_parser.add_argument("--size-kw", type=float, help="System size in kW")
    elig_parser.add_argument("--installer-approved", choices=["yes", "no"])
    elig_parser.add_argument("--tier", choices=["community", "household", "commercial"])

    extract_parser = sub.add_parser("extract-slots", help="Extract eligibility slots (1 LLM call)")
    extract_parser.add_argument("text")
    extract_parser.add_argument("--no-cache", action="store_true")

    ask_parser = sub.add_parser("ask", help="Ask the Copilot (interactive; --once for one message)")
    ask_parser.add_argument("--once", metavar="QUESTION", help="Handle one message and exit")
    ask_parser.add_argument("--debug", action="store_true", help="Print the trace and usage")

    eval_parser = sub.add_parser("eval", help="Run the held-out evaluation set")
    eval_parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    eval_parser.add_argument("--ids", help="Comma-separated question ids")
    eval_parser.add_argument("--tags", help="Comma-separated tags (any match)")
    eval_parser.add_argument("--workers", type=int, default=3)
    eval_parser.add_argument("--repeat", type=int, default=1)
    eval_parser.add_argument("--out", type=Path, help="Run folder (default eval/results/<UTC time>/)")
    eval_parser.add_argument("--mode", choices=["pipeline", "full-context"], default="pipeline")

    summarize_parser = sub.add_parser("eval-summarize", help="Merge a filled grade sheet")
    summarize_parser.add_argument("run_dir", type=Path)
    summarize_parser.add_argument("--grades", type=Path, required=True)
    args = parser.parse_args(argv)
    if getattr(args, "repeat", 1) < 1 or getattr(args, "workers", 1) < 1:
        parser.error("--repeat and --workers must be at least 1")
    if getattr(args, "top_k", None) is not None and args.top_k < 1:
        parser.error("--top-k must be at least 1")

    if args.command == "check-llm":
        return check_llm()
    if args.command == "ingest":
        return run_ingest()
    if args.command == "search":
        return run_search(args.query, args.category, args.top_k, args.json)
    if args.command == "classify":
        return run_classify(args.query, not args.no_cache)
    if args.command == "retrieve":
        return run_retrieve(args.query, args.force_category, args.top_k, not args.no_cache)
    if args.command == "calibrate":
        return run_calibrate(args.dev_set, args.workers, not args.no_cache)
    if args.command == "eligibility":
        return run_eligibility_cli(args)
    if args.command == "extract-slots":
        return run_extract_slots(args.text, not args.no_cache)
    if args.command == "ask":
        return run_ask(args.once, args.debug)
    if args.command == "eval":
        return run_eval_cli(args)
    if args.command == "eval-summarize":
        return run_eval_summarize(args.run_dir, args.grades)
    return 2


if __name__ == "__main__":
    sys.exit(main())
