# Evaluation

Every automatic check compares something the system did (category, retrieved documents, cited sources,
outcome, tool call, review flag) with what the question file expects, plus one fixed no-`$` rule. There is no
LLM judge and there are no wording checks. Whether a reply's content is correct is **not** scored automatically; see
[What is not automatically checked](#what-is-not-automatically-checked).

## What is here

| File | Purpose |
|---|---|
| `questions.yaml` | Evaluation set: 20 questions. A comment above each one says what it tests. |
| `dev_queries.yaml` | Development set (30 queries) used only for `calibrate`; never scored here. |
| `RUBRIC.md` | One-page rubric for the optional hand grading. |
| `results/` | Run folders (git-ignored). |

## Provenance and limitations

- The question set was written after the first end-to-end demo runs, so it is not blind. It is a behaviour
  and regression check, not an accuracy benchmark.
- **Small n**: 20 questions. All results are counts (`n/N`), not rates, and N differs per check because a
  check is only scored where the question specifies it. One question changes a count noticeably.
- **Classifier confidence is self-reported** by the LLM and uncalibrated; `category_ok` checks only the label.
- LLM output varies run to run even at temperature 0; use `--repeat N` to see which questions are unstable.

## The checks

| Check | Meaning |
|---|---|
| `category_ok` | The classifier category is one of `category_any`. |
| `retrieval_ok` | Every doc in `sources` is among the retrieved chunks. |
| `cited_ok` | When the outcome is `answered`, at least one doc in `sources` is cited in the reply. |
| `outcome_ok` | The final outcome is in `outcome_in` (answered, abstained, declined_out_of_scope, eligible_preliminary, ineligible, needs_info ...). Every turn that sets `expect_outcome` is checked too. |
| `tool_ok` | The eligibility service was called, or not, as expected. |
| `escalation_ok` | The reply was flagged for human review, as `escalated` expects. Set on q02 and q09 only. |
| `hard_gate_ok` | Fixed rule, not set per question: an `ineligible`, `tier_not_household`, `needs_info`, `invalid_input` or `tool_error` reply contains no `$`, on any turn. |

`auto_pass` means no error and no check is False.

- Checks apply to the **final turn**, except where the table says otherwise.
- `category_ok` uses the **last classified** category in the conversation: when a turn only supplies slots
  for a pending eligibility question, the agent does not re-classify it.
- `retrieval_ok` uses the doc stems of the chunks the final turn actually retrieved for its answer.
- `tool_ok` is true if the eligibility service was called in **any** turn when expected.
- `cited_ok` is skipped unless the outcome is `answered`: an abstention cites nothing, and whether abstaining
  was right is `outcome_ok`'s job (q02 and q06 allow it).
- A provider failure (`service_unavailable`) or a crash is recorded as `error` for that question; it never
  stops the run, and an errored question cannot pass.

## What is not automatically checked

- **Reply wording and correctness.** A reply can pass every check and still be wrong.
- **Dollar amounts in replies.** Figures are not compared with the reference. The only amount rule is
  `hard_gate_ok`, which sees a literal `$` in non-eligible replies and nothing else.
- **The human-review flag on other questions.** Only q02 and q09 set `escalated`. It is recorded in
  `results.json` for the rest but not scored.
- **Safety wording.** For example, a suggested reset on an E07 fault is not detected.

Two questions keep a flag guard: `escalation_ok` fails q02 and q09 if the reply is not flagged for review.
It does not read the reply, so q02's wrong flat "No" or a suggested reset on q09 passes if the reply is flagged.

Reply wording and facts are not auto-checked on any question. So these cannot be detected automatically: a
wrong 15-business-day deadline on q15, a claim that multi-family housing qualifies on q12, an invented dollar
figure on q06, "you would normally get" wording without a `$` on q17, and a wrong figure or fact on q01, q03,
q04, q05, q07, q08, q10, q11, q13, q14, q16 and q18. The comment above each question in `questions.yaml` says
what is not auto-checked for it.

## How to run

```
python -m sungrid_copilot.cli eval --workers 3                 # full run (real LLM calls)
python -m sungrid_copilot.cli eval --ids q09,q10               # a subset
python -m sungrid_copilot.cli eval --tags eligibility
python -m sungrid_copilot.cli eval --repeat 3                  # stability across repeats
python -m sungrid_copilot.cli eval --mode full-context         # baseline: whole KB in one prompt
```

Runs use the same member-session path as `ask` (LLM caches off), so every run makes real calls.

`--mode full-context` is a comparison, not the product: all chunks go to the same composer in one prompt,
with no classification, filter or retrieval. Eligibility and `non_relevant` questions are skipped, and only
`outcome_ok` and `cited_ok` are scored.

## How to read the outputs

Each run folder contains:

- `summary.md`: run details, counts per check (overall and by tag), failing questions, latency, tokens and
  cost. With `--repeat`, counts are from repeat 1 and a stability section is added.
- `results.json`: everything per question, including traces and per-call tokens.
- `grade_sheet.csv`: one row per question for the optional hand grading.
- `queries.jsonl`: the agent's privacy-preserving log for the run.

Copy the final run's `summary.md` into `submission/` by hand.

## Optional human spot check

Hand grading is the only check of reply content.

1. Copy `grade_sheet.csv` from the run folder and fill `correct`, `grounded` and `notes` using `RUBRIC.md`.
2. Merge: `python -m sungrid_copilot.cli eval-summarize eval/results/<run> --grades <filled.csv>`.
   This adds hand-graded counts and every question graded 0 to the run's `summary.md` (re-running replaces
   the section).

## Future improvements

- An LLM judge that compares replies with the `reference`.
- Human feedback to validate that judge.
- A second grader.
- Review-flag expectations on more questions, and a fuller no-dollar check.
- A larger question set, written before looking at results.
- Claim-level grounding checks.
