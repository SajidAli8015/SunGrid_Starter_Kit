# Evaluation

## What is here

| File | Purpose |
|---|---|
| `questions.yaml` | Held-out evaluation set: 20 questions (fixed content, not edited). |
| `dev_queries.yaml` | Development set (30 queries) used only for `calibrate`; never scored here. |
| `RUBRIC.md` | One-page rubric for hand grading. |
| `results/` | Run folders (git-ignored). |

## Provenance and limitations

- The held-out set was written **after** the first end-to-end demo runs, so it is not fully blind.
  Questions tagged `seen_in_demo` closely mirror a demo query. Nothing (prompts, thresholds, manifest,
  code) was tuned against it before the baseline run; later changes must be recorded as separate,
  labelled runs.
- **Small n**: 20 questions. All results are counts (`n/N`), not rates, and N differs per check because a
  check is only scored where the question specifies it. One question changes a count noticeably.
- **Regexes are a coarse proxy**: `must_contain` / `must_not_contain` check wording, not meaning. A reply can
  pass them and still be wrong, which is why every run has a hand-graded sheet.
- **Classifier confidence is self-reported** by the LLM and uncalibrated; `category_ok` checks only the label.
- LLM output varies run to run even at temperature 0; use `--repeat N` to see which questions are unstable.

## How the checks are applied

- Checks apply to the **final turn**. `outcome_ok` also checks every turn that sets `expect_outcome`.
- `category_ok` uses the **last classified** category in the conversation: when a turn only supplies slots
  for a pending eligibility question, the agent does not re-classify it.
- `retrieval_all` / `retrieval_any` use the doc stems of the chunks the final turn actually retrieved for
  its answer. `cited_any` compares against the cited sources and is reported but not part of `auto_pass`.
- `tool_ok` is true if the eligibility service was called in **any** turn when expected.
- `hard_gate_ok` is applied to every question and every turn: an `ineligible`, `tier_not_household`,
  `needs_info`, `invalid_input` or `tool_error` reply must contain no `$`.
- A provider failure (`service_unavailable`) or a crash is recorded as `error` for that question; it never
  stops the run, and an errored question cannot pass.

## How to run

```
python -m sungrid_copilot.cli eval --workers 3                 # full baseline (real LLM calls)
python -m sungrid_copilot.cli eval --ids q09,q10               # a subset
python -m sungrid_copilot.cli eval --tags eligibility
python -m sungrid_copilot.cli eval --repeat 3                  # stability across repeats
python -m sungrid_copilot.cli eval --mode full-context         # baseline: whole KB in one prompt
```

Runs use the same member-session path as `ask` (LLM caches off), so every run makes real calls. Each run
folder contains `results.json` (everything per question, including traces and per-call tokens),
`summary.md`, `grade_sheet.csv` and `queries.jsonl` (the agent's privacy-preserving log for the run).

`--mode full-context` is a comparison, not the product: all chunks go to the same composer in one prompt,
with no classification, filter or retrieval. Eligibility and `non_relevant` questions are skipped, and only
the text checks are scored.

## How to grade

1. Copy `grade_sheet.csv` from the run folder and fill `correct`, `grounded` and `notes` using `RUBRIC.md`.
2. Merge: `python -m sungrid_copilot.cli eval-summarize eval/results/<run> --grades <filled.csv>`.
   This adds hand-graded counts and every question graded 0 to the run's `summary.md` (re-running replaces
   the section).
3. Copy the final run's `summary.md` into `submission/` by hand.
