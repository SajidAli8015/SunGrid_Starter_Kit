"""Calibrate retrieval thresholds on the development query set.

Prints suggestions only; it never writes thresholds to config. The classifier calls are cached,
so a second run makes no new LLM calls. The robustness experiment uses no LLM at all.
"""

from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from sungrid_copilot.categories import NON_RELEVANT, CategorySet
from sungrid_copilot.classify import ClassificationResult, Classifier, ClassifyOutcome
from sungrid_copilot.llm import LLMError
from sungrid_copilot.retrieval import UNFILTERED_CLEARLY_BETTER, Retriever

DEFAULT_MARGINS = [round(0.02 + 0.01 * i, 2) for i in range(9)]  # 0.02 .. 0.10


class DevQuery(BaseModel):
    id: str
    query: str
    expected_category: str
    expected_sources: list[str] = Field(default_factory=list)
    expect_eligibility_check: bool = False
    tags: list[str] = Field(default_factory=list)

    @property
    def in_scope(self) -> bool:
        return self.expected_category != NON_RELEVANT


def load_dev_set(path: Path, categories: CategorySet, doc_ids: set[str]) -> list[DevQuery]:
    with path.open(encoding="utf-8") as f:
        queries = [DevQuery.model_validate(q) for q in (yaml.safe_load(f) or {}).get("queries", [])]
    problems = []
    for q in queries:
        if q.expected_category not in categories.query_labels:
            problems.append(f"{q.id}: unknown category '{q.expected_category}'")
        problems += [f"{q.id}: unknown source '{s}'" for s in q.expected_sources if s not in doc_ids]
    ids = [q.id for q in queries]
    problems += [f"duplicate id '{i}'" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if problems:
        raise ValueError(f"Invalid dev set {path}: " + "; ".join(problems))
    return queries


def _synthetic(category: str) -> ClassificationResult:
    """A fully confident label, to test retrieval with no LLM involved."""
    return ClassificationResult(
        category=category, confidence=1.0, needs_eligibility_check=False, rationale="calibration"
    )


def _classify_all(
    classifier: Classifier, queries: list[DevQuery], workers: int, use_cache: bool
) -> dict[str, ClassifyOutcome | str]:
    def one(q: DevQuery) -> ClassifyOutcome | str:
        try:
            return classifier.classify(q.query, use_cache=use_cache)
        except LLMError as e:
            return f"ERROR: {e}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip((q.id for q in queries), pool.map(one, queries)))


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": round(min(values), 4),
        "median": round(statistics.median(values), 4),
        "max": round(max(values), 4),
    }


def _best_ceiling(in_scope: list[float], out_of_scope: list[float]) -> dict:
    """Ceiling t: decline-eligible if top-1 < t. Errors = in-scope below t + out-of-scope at/above t."""
    if not in_scope or not out_of_scope:
        return {"separable": None, "suggested": None, "errors": None}
    if max(out_of_scope) < min(in_scope):
        return {
            "separable": True,
            "suggested": round((max(out_of_scope) + min(in_scope)) / 2, 3),
            "gap": round(min(in_scope) - max(out_of_scope), 4),
            "errors": 0,
        }
    points = sorted(set(in_scope + out_of_scope))
    candidates = [(a + b) / 2 for a, b in zip(points, points[1:])] + [points[0], points[-1] + 1e-6]

    def errors(t: float) -> int:
        return sum(s < t for s in in_scope) + sum(s >= t for s in out_of_scope)

    # Ties go to the lowest ceiling: wrongly declining an in-scope question is worse than
    # answering an out-of-scope one (grounding can still abstain).
    best = min(candidates, key=lambda t: (errors(t), t))
    return {"separable": False, "suggested": round(best, 3), "errors": errors(best)}


def _hit(result, expected: list[str]) -> bool:
    return any(h.chunk.doc_id in expected for h in result.hits)


def _robustness(retriever: Retriever, queries: list[DevQuery], categories: CategorySet) -> dict:
    """(a) correct category, (b) each wrong category with fallback, (c) wrong without fallback."""
    a = b = c = a_fires = b_fires = 0
    n_a = n_wrong = 0
    misses: list[dict] = []
    for q in queries:
        correct = retriever.retrieve(q.query, _synthetic(q.expected_category))
        n_a += 1
        a += _hit(correct, q.expected_sources)
        a_fires += correct.fallback_reason == UNFILTERED_CLEARLY_BETTER
        for wrong in (name for name in categories.names if name != q.expected_category):
            with_fb = retriever.retrieve(q.query, _synthetic(wrong))
            without_fb = retriever.retrieve(q.query, _synthetic(wrong), fallback=False)
            n_wrong += 1
            b += _hit(with_fb, q.expected_sources)
            c += _hit(without_fb, q.expected_sources)
            b_fires += with_fb.fallback_reason == UNFILTERED_CLEARLY_BETTER
            if not _hit(with_fb, q.expected_sources):
                misses.append({"id": q.id, "forced": wrong, "margin": _round(with_fb.margin)})
    return {
        "a_correct_category": {"hits": a, "n": n_a, "fallback_fired": a_fires},
        "b_wrong_with_fallback": {"hits": b, "n": n_wrong, "fallback_fired": b_fires},
        "c_wrong_without_fallback": {"hits": c, "n": n_wrong},
        "b_misses": misses,
    }


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def run_calibration(
    classifier: Classifier,
    retriever: Retriever,
    queries: list[DevQuery],
    *,
    workers: int = 3,
    use_cache: bool = True,
    margins: list[float] = DEFAULT_MARGINS,
) -> dict:
    categories = retriever.categories
    outcomes = _classify_all(classifier, queries, workers, use_cache)

    # 1. Classifier accuracy, and the decline decision at current settings.
    rows, misses = [], []
    for q in queries:
        outcome = outcomes[q.id]
        retrieved = retriever.retrieve(q.query, _synthetic(q.expected_category))
        row = {
            "id": q.id,
            "query": q.query,
            "expected": q.expected_category,
            "expect_eligibility_check": q.expect_eligibility_check,
            "unfiltered_top_score": _round(retrieved.unfiltered_top_score),
        }
        if isinstance(outcome, str):
            row.update(got="ERROR", error=outcome)
        else:
            result = outcome.result
            actual = retriever.retrieve(q.query, result)
            row.update(
                got=result.category,
                confidence=result.confidence,
                needs_eligibility_check=result.needs_eligibility_check,
                rationale=result.rationale,
                cached=outcome.cached,
                would_decline=retriever.should_decline(result, actual),
                fallback_reason=actual.fallback_reason,
            )
        rows.append(row)
        if row["got"] != q.expected_category:
            misses.append({k: row.get(k) for k in ("id", "query", "expected", "got", "confidence")})

    ok = [r for r in rows if r["got"] != "ERROR"]
    in_scope_ids = {q.id for q in queries if q.in_scope}
    classification = {
        "category_correct": sum(r["got"] == r["expected"] for r in rows),
        "n": len(rows),
        "misses": misses,
        "eligibility_correct": sum(
            r.get("needs_eligibility_check") == r["expect_eligibility_check"] for r in ok
        ),
        "eligibility_misses": [
            {k: r.get(k) for k in ("id", "query", "expect_eligibility_check", "needs_eligibility_check")}
            for r in ok
            if r.get("needs_eligibility_check") != r["expect_eligibility_check"]
        ],
        "errors": len(rows) - len(ok),
        "llm_calls": sum(1 for o in outcomes.values() if not isinstance(o, str) and not o.cached),
        "cached": sum(1 for o in outcomes.values() if not isinstance(o, str) and o.cached),
        "declined_out_of_scope": sum(
            bool(r.get("would_decline")) for r in rows if r["id"] not in in_scope_ids
        ),
        "declined_in_scope": [r["id"] for r in rows if r["id"] in in_scope_ids and r.get("would_decline")],
    }

    # 2. Unfiltered top-1 score distributions and a non_relevant ceiling.
    in_scores = [r["unfiltered_top_score"] for r in rows if r["id"] in in_scope_ids]
    out_scores = [r["unfiltered_top_score"] for r in rows if r["id"] not in in_scope_ids]
    scores = {
        "in_scope": _stats(in_scores),
        "out_of_scope": _stats(out_scores),
        "ceiling": _best_ceiling(in_scores, out_scores),
    }

    # 3 and 4. Retrieval robustness (no LLM), swept over fallback margins.
    with_sources = [q for q in queries if q.in_scope and q.expected_sources]
    sweep = []
    for m in margins:
        r = _robustness(
            retriever.with_settings(retriever.settings.model_copy(update={"fallback_margin": m})),
            with_sources,
            categories,
        )
        sweep.append({"margin": m, **r})
    current = _robustness(retriever, with_sources, categories)
    # Most robust to a wrong label without losing correct-label hits; ties go to the largest
    # margin, so the fallback fires least when the label is right.
    best = max(
        sweep,
        key=lambda s: (
            s["b_wrong_with_fallback"]["hits"] + s["a_correct_category"]["hits"],
            s["margin"],
        ),
    )

    return {
        "settings": retriever.settings.model_dump(),
        "classifier": {"model": classifier.client.model, "prompt_hash": classifier.prompt_hash},
        "classification": classification,
        "scores": scores,
        "robustness_current": {"margin": retriever.settings.fallback_margin, **current},
        "margin_sweep": sweep,
        "suggested": {
            "fallback_margin": best["margin"],
            "non_relevant_score_ceiling": scores["ceiling"]["suggested"],
        },
        "queries": rows,
    }


def format_summary(report: dict) -> str:
    c, s, rc = report["classification"], report["scores"], report["robustness_current"]
    out = [
        f"Classifier: {report['classifier']['model']} (prompt {report['classifier']['prompt_hash']}); "
        f"{c['llm_calls']} LLM call(s), {c['cached']} cached, {c['errors']} error(s)",
        "",
        "1. Classification",
        f"   category: {c['category_correct']}/{c['n']} correct",
    ]
    for m in c["misses"]:
        conf = "-" if m["confidence"] is None else f"{m['confidence']:.2f}"
        out.append(f"     MISS {m['id']}: expected {m['expected']}, got {m['got']} ({conf}): {m['query']}")
    out.append(f"   needs_eligibility_check: {c['eligibility_correct']}/{c['n'] - c['errors']} correct")
    for m in c["eligibility_misses"]:
        out.append(
            f"     MISS {m['id']}: expected {m['expect_eligibility_check']}, "
            f"got {m['needs_eligibility_check']}: {m['query']}"
        )
    out.append(
        f"   would decline (current settings): {c['declined_out_of_scope']}/"
        f"{s['out_of_scope'].get('n', 0)} out-of-scope; in-scope wrongly declined: "
        f"{c['declined_in_scope'] or 'none'}"
    )

    ceiling = s["ceiling"]
    out += [
        "",
        "2. Unfiltered top-1 scores",
        f"   in-scope:     {_fmt_stats(s['in_scope'])}",
        f"   out-of-scope: {_fmt_stats(s['out_of_scope'])}",
    ]
    if ceiling["separable"]:
        out.append(
            f"   separable (gap {ceiling['gap']}): suggested non_relevant_score_ceiling = "
            f"{ceiling['suggested']}"
        )
    elif ceiling["separable"] is False:
        out.append(
            f"   OVERLAP: no ceiling separates them; best single ceiling {ceiling['suggested']} "
            f"still misplaces {ceiling['errors']} query(ies)"
        )

    def counts(r: dict) -> str:
        a, b, cc = r["a_correct_category"], r["b_wrong_with_fallback"], r["c_wrong_without_fallback"]
        return f"(a) {a['hits']}/{a['n']}   (b) {b['hits']}/{b['n']}   (c) {cc['hits']}/{cc['n']}"

    out += [
        "",
        f"3. Retrieval robustness, expected source in top-{report['settings']['top_k']} "
        f"(no LLM; margin {rc['margin']})",
        "   (a) correct category  (b) wrong category + fallback  (c) wrong category, no fallback",
        f"   {counts(rc)}",
        "",
        "4. Margin sweep",
        "   margin  (a) hits  fallback fired on (a)  (b) hits  fallback fired on (b)",
    ]
    for row in report["margin_sweep"]:
        a, b = row["a_correct_category"], row["b_wrong_with_fallback"]
        out.append(
            f"   {row['margin']:.2f}    {a['hits']:>2}/{a['n']:<3}   {a['fallback_fired']:>2}/{a['n']:<17}"
            f"   {b['hits']:>2}/{b['n']:<3}   {b['fallback_fired']:>2}/{b['n']}"
        )
    sug = report["suggested"]
    out += [
        "",
        "5. Suggestions (not written to config)",
        f"   fallback_margin: {sug['fallback_margin']}  (current {report['settings']['fallback_margin']})",
        f"   non_relevant_score_ceiling: {sug['non_relevant_score_ceiling']}  "
        f"(current {report['settings']['non_relevant_score_ceiling']})",
    ]
    return "\n".join(out)


def _fmt_stats(st: dict) -> str:
    if not st.get("n"):
        return "n=0"
    return f"n={st['n']}  min {st['min']:.3f}  median {st['median']:.3f}  max {st['max']:.3f}"


def save_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
