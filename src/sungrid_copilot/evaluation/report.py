"""Evaluation outputs: results.json, summary.md, grade_sheet.csv, and the hand-grade merge.

Every figure is a count n/N over a small, hand-written question set, never a rate.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sungrid_copilot.config import PROJECT_ROOT, Settings
from sungrid_copilot.evaluation.checks import CHECK_NAMES, INFORMATIONAL
from sungrid_copilot.evaluation.schema import EvalSet, Question, provenance_note

GRADE_COLUMNS = [
    "id", "question", "final_answer", "cited_sources", "auto_pass", "failed_checks",
    "reference", "correct", "grounded", "notes",
]
HAND_GRADING_HEADER = "## Hand grading"


# ----------------------------------------------------------------------------- run metadata


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def build_meta(
    settings: Settings, questions_path: Path, *, mode: str, repeat: int, workers: int, model: str
) -> dict:
    status = _git("status", "--porcelain")
    return {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": None if status is None else bool(status),
        "mode": mode,
        "repeat": repeat,
        "workers": workers,
        "provider": settings.llm.provider,
        "model": model,
        "embedding_model": settings.embedding.model,
        "retrieval": settings.retrieval.model_dump(),
        "classifier": {"max_tokens": settings.classifier.max_tokens},
        "llm_cache": settings.agent.use_llm_cache,
        "questions_file": questions_path.relative_to(PROJECT_ROOT).as_posix()
        if questions_path.is_relative_to(PROJECT_ROOT) else str(questions_path),
        "questions_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
        "provenance": provenance_note(questions_path),
    }


def save_results(run_dir: Path, meta: dict, records: list[dict]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "results.json"
    path.write_text(json.dumps({"meta": meta, "records": records}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_results(run_dir: Path) -> tuple[dict, list[dict]]:
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    return data["meta"], data["records"]


# ----------------------------------------------------------------------------- summary


def _scored(records: list[dict]) -> list[dict]:
    """First repeat, excluding skipped questions."""
    return [r for r in records if r.get("repeat", 1) == 1 and not r.get("skipped")]


def check_counts(records: list[dict]) -> dict[str, tuple[int, int]]:
    counts = {}
    for name in CHECK_NAMES:
        scored = [r["checks"].get(name) for r in records if r["checks"].get(name) is not None]
        counts[name] = (sum(1 for v in scored if v), len(scored))
    counts["auto_pass"] = (sum(1 for r in records if r["auto_pass"]), len(records))
    return counts


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]  # nearest rank


def _fmt(n_of: tuple[int, int]) -> str:
    n, total = n_of
    return f"{n}/{total}" if total else "n/a"


def build_summary(meta: dict, records: list[dict], eval_set: EvalSet) -> str:
    scored = _scored(records)
    n = len(scored)
    baseline = meta["mode"] == "full-context"
    title = (
        "# Evaluation summary: BASELINE, full-context (not the product)"
        if baseline else "# Evaluation summary: pipeline"
    )
    r = meta["retrieval"]
    dirty = {True: "yes", False: "no", None: "unknown"}[meta["git_dirty"]]
    lines = [
        title,
        "",
        f"- Date (UTC): {meta['date_utc']}",
        f"- Git commit: `{meta['git_commit'] or 'unknown'}` (working tree dirty: {dirty})",
        f"- Provider / model: {meta['provider']} / {meta['model']}",
        f"- Embedding model: {meta['embedding_model']}",
        f"- Retrieval: top_k={r['top_k']}, classifier_min_conf={r['classifier_min_conf']}, "
        f"non_relevant_min_conf={r['non_relevant_min_conf']}, fallback_margin={r['fallback_margin']}, "
        f"non_relevant_score_ceiling={r['non_relevant_score_ceiling']}",
        f"- Classifier: max_tokens={meta['classifier']['max_tokens']}; LLM caches "
        f"{'on' if meta['llm_cache'] else 'off'}",
        f"- Questions: `{meta['questions_file']}` (sha256 `{meta['questions_sha256'][:16]}...`), "
        f"{n} scored, repeat={meta['repeat']}, workers={meta['workers']}",
        f"- {meta['provenance'] or 'Provenance: not stated'}",
        "",
        f"> The sample is small ({n} questions). Every figure below is a count of questions (n/N), "
        "not a rate, and N differs per check because a check is only scored where the question "
        "specifies it. Regexes are a coarse proxy for correctness; see the hand grading.",
    ]
    if baseline:
        lines += [
            "",
            "> BASELINE: all knowledge-base chunks in one prompt to the same composer, with no "
            "classification, filtering or retrieval. Only text checks are scored; retrieval, category, "
            "tool and escalation checks are N/A.",
        ]

    counts = check_counts(scored)
    errors = sum(1 for x in scored if x.get("error"))
    lines += ["", "## Automated checks", "", "| check | passed |", "|---|---|"]
    for name in CHECK_NAMES:
        note = " (informational, not in auto_pass)" if name in INFORMATIONAL else ""
        lines.append(f"| {name}{note} | {_fmt(counts[name])} |")
    lines += [f"| **auto_pass** | **{_fmt(counts['auto_pass'])}** |", f"| errors | {errors}/{n} |"]

    by_tag: dict[str, list[dict]] = defaultdict(list)
    for rec in scored:
        for tag in rec["tags"]:
            by_tag[tag].append(rec)
    lines += ["", "## By tag", "", "| tag | auto_pass | " + " | ".join(CHECK_NAMES) + " |",
              "|---|---|" + "---|" * len(CHECK_NAMES)]
    for tag in sorted(by_tag):
        c = check_counts(by_tag[tag])
        lines.append(
            f"| {tag} | {_fmt(c['auto_pass'])} | " + " | ".join(_fmt(c[k]) for k in CHECK_NAMES) + " |"
        )

    failing = [x for x in scored if not x["auto_pass"]]
    lines += ["", f"## Failing questions ({len(failing)}/{n})", ""]
    if not failing:
        lines.append("None.")
    for rec in failing:
        lines.append(f"- **{rec['id']}** ({', '.join(rec['tags'])})")
        if rec.get("error"):
            lines.append(f"  - error: {rec['error']}")
        for name, detail in rec["check_details"].items():
            marker = " (informational)" if name in INFORMATIONAL else ""
            lines.append(f"  - `{name}`{marker}: {detail}")
    informational_only = [
        x for x in scored if x["auto_pass"] and any(k in INFORMATIONAL for k in x["check_details"])
    ]
    for rec in informational_only:
        lines.append(f"- {rec['id']} passed, but: " + "; ".join(
            f"`{k}`: {v}" for k, v in rec["check_details"].items()
        ))

    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in scored:
        groups[rec.get("outcome") or "error"].append(rec)
    lines += [
        "", "## Latency, calls and tokens by outcome", "",
        "| outcome | n | median latency (s) | p95 latency (s) | mean LLM calls | mean tokens in | mean tokens out |",
        "|---|---|---|---|---|---|---|",
    ]
    for outcome in sorted(groups):
        g = groups[outcome]
        lat = [x.get("latency_ms", 0) / 1000 for x in g]
        lines.append(
            f"| {outcome} | {len(g)} | {statistics.median(lat):.1f} | {_p95(lat):.1f} | "
            f"{statistics.mean(x.get('llm_call_count', 0) for x in g):.1f} | "
            f"{statistics.mean(x.get('tokens_in', 0) for x in g):.0f} | "
            f"{statistics.mean(x.get('tokens_out', 0) for x in g):.0f} |"
        )
    tin = sum(x.get("tokens_in", 0) for x in scored)
    tout = sum(x.get("tokens_out", 0) for x in scored)
    lines += ["", "## Tokens and cost", "", f"- Total tokens: {tin} in / {tout} out over {n} questions"]
    costs = [x.get("estimated_cost_usd") for x in scored]
    if n and all(c is not None for c in costs):
        total = sum(costs)
        lines += [
            f"- Estimated cost: ${total:.4f} total, ${total / n:.5f} per question",
            f"- Projection: ${total / n * 1000:.2f} per 1,000 queries at this question mix "
            "(a multi-turn question counts as one query)",
        ]

    if meta["repeat"] > 1:
        lines += build_stability(records)
    skipped = [x for x in records if x.get("skipped") and x.get("repeat", 1) == 1]
    if skipped:
        lines += ["", f"## Skipped ({len(skipped)})", ""]
        lines += [f"- {x['id']}: {x['skipped']}" for x in skipped]
    return "\n".join(lines) + "\n"


def build_stability(records: list[dict]) -> list[str]:
    runs: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        if not rec.get("skipped"):
            runs[rec["id"]].append(rec)
    unstable = [
        qid for qid, rs in runs.items()
        if len({x.get("outcome") for x in rs}) > 1 or len({x["auto_pass"] for x in rs}) > 1
    ]
    lines = [
        "", "## Stability across repeats", "",
        f"- Same outcome and same auto_pass in every repeat: {len(runs) - len(unstable)}/{len(runs)}",
        f"- Counts above are from repeat 1.",
    ]
    for qid in unstable:
        detail = ", ".join(f"r{x['repeat']}: {x.get('outcome')}/{'pass' if x['auto_pass'] else 'fail'}"
                           for x in runs[qid])
        lines.append(f"  - unstable {qid}: {detail}")
    return lines


# ----------------------------------------------------------------------------- grade sheet


def write_grade_sheet(path: Path, records: list[dict], eval_set: EvalSet) -> None:
    by_id: dict[str, Question] = {q.id: q for q in eval_set.questions}
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GRADE_COLUMNS)
        writer.writeheader()
        for rec in _scored(records):
            q = by_id[rec["id"]]
            writer.writerow({
                "id": rec["id"],
                "question": q.text,
                "final_answer": rec.get("final_text", ""),
                "cited_sources": "; ".join(rec.get("cited_stems", [])),
                "auto_pass": rec["auto_pass"],
                "failed_checks": "; ".join(k for k in rec["check_details"] if k not in INFORMATIONAL)
                + ("; error" if rec.get("error") else ""),
                "reference": q.reference.strip(),
                "correct": "",
                "grounded": "",
                "notes": "",
            })


def write_outputs(run_dir: Path, meta: dict, records: list[dict], eval_set: EvalSet) -> None:
    save_results(run_dir, meta, records)
    (run_dir / "summary.md").write_text(build_summary(meta, records, eval_set), encoding="utf-8")
    write_grade_sheet(run_dir / "grade_sheet.csv", records, eval_set)


class GradeError(Exception):
    """The filled grade sheet is malformed."""


def merge_grades(run_dir: Path, grades_csv: Path) -> str:
    """Add hand-graded counts to summary.md (replacing a previous hand-grading section)."""
    _, records = load_results(run_dir)
    known = {r["id"] for r in _scored(records)}
    with grades_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    problems = []
    for row in rows:
        if row.get("id") not in known:
            problems.append(f"unknown id {row.get('id')!r}")
        if (row.get("correct") or "").strip() not in {"", "0", "1"}:
            problems.append(f"{row.get('id')}: correct must be 0, 1 or blank")
        if (row.get("grounded") or "").strip().lower() not in {"", "0", "1", "n/a", "na"}:
            problems.append(f"{row.get('id')}: grounded must be 0, 1, n/a or blank")
    if problems:
        raise GradeError("; ".join(problems))

    correct = [r for r in rows if r["correct"].strip() in {"0", "1"}]
    grounded = [r for r in rows if r["grounded"].strip() in {"0", "1"}]
    ungraded = [r["id"] for r in rows if not r["correct"].strip()]
    section = [
        HAND_GRADING_HEADER,
        "",
        f"- correct: {sum(r['correct'].strip() == '1' for r in correct)}/{len(correct)}",
        f"- grounded: {sum(r['grounded'].strip() == '1' for r in grounded)}/{len(grounded)} "
        "(declines and deterministic eligibility text are n/a)",
        f"- not yet graded: {', '.join(ungraded) or 'none'}",
        "",
        "Graded 0:",
    ]
    zeros = [r for r in rows if "0" in (r["correct"].strip(), r["grounded"].strip())]
    for r in zeros:
        which = [k for k in ("correct", "grounded") if r[k].strip() == "0"]
        section.append(f"- {r['id']} ({', '.join(which)}): {r.get('notes', '').strip() or 'no note'}")
    if not zeros:
        section.append("- none")

    summary_path = run_dir / "summary.md"
    text = summary_path.read_text(encoding="utf-8")
    if HAND_GRADING_HEADER in text:
        text = text.split(HAND_GRADING_HEADER)[0].rstrip() + "\n"
    text = text.rstrip() + "\n\n" + "\n".join(section) + "\n"
    summary_path.write_text(text, encoding="utf-8")
    return text
