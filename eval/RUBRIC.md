# Hand-grading rubric

Hand grading is the only check of reply content: the automatic checks compare behaviour (category, retrieval,
citations, outcome, tool call, review flag), not what the reply says. It is an optional spot check.

Fill the last three columns of a run's `grade_sheet.csv`, one row per question, then merge it with
`python -m sungrid_copilot.cli eval-summarize <run_dir> --grades <filled_csv>`.

## `correct` (0 or 1)

- **1** if the key facts match the `reference` and nothing in the reply contradicts the knowledge base.
- For abstentions and declines, 1 means the behaviour matches the reference (for example, an abstention
  where the knowledge base genuinely does not contain the answer, or a decline for an out-of-scope
  question). An abstention where the knowledge base does contain the answer is 0.
- Any invented fact, number or date is 0, even if the rest is right.
- For eligibility replies, judge the outcome and any appended "what happens next" text against the
  reference; the deterministic part is fixed text.

## `grounded` (0, 1 or `n/a`)

- **1** if every claim in the reply is supported by a cited source and citations are present.
- **0** if any claim is not supported by the cited sources (even if it happens to be true), or a
  substantive answer has no citations.
- **n/a** for declines and for the deterministic eligibility text (clarifying questions, eligibility
  decisions without appended text, tier and error messages). If an eligibility reply has appended KB text,
  grade that part.

## Notes

- Write a note for **every 0**: what was wrong, in one line (for example "says only Household members vote;
  Voting Eligibility says Community members get one vote").
- A question that passes the automated checks can still fail by hand: they do not read the reply's content.
- Grade the final turn's reply; for multi-turn questions, also note if an earlier turn misbehaved.
