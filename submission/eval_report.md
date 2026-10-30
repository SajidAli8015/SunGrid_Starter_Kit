# Evaluation report

I ran the full evaluation on 2026-10-30 at git commit `f06112d` (working tree clean), using `gpt-4o` on Azure OpenAI
and `BAAI/bge-small-en-v1.5` embeddings. The raw output is in `eval_summary.md` in this folder.

All figures are counts of questions (n/N), not rates. With 20 questions the numbers are indicative only. **This
report relies on automatic checks. I have not yet graded the replies by hand**, and section 5 explains what that
leaves open.

## 1. The evaluation set

- 20 questions in `eval/questions.yaml`: 15 knowledge questions covering all five categories, 3 eligibility
  questions (eligible, ineligible, multi-turn slot filling) and 2 out-of-scope questions.
- It includes the traps the brief names: two questions that depend on document 06 (the ambiguous one), a terse
  fault-code query that must not be declined, a question whose answer is not in the knowledge base (q02), an
  arithmetic cap (q05) and a time-qualified statistic (q13). Each question has a comment saying what it tests.
- **Provenance.** I wrote the set after my first end-to-end demo runs, so it is not blind. I treat it as a
  behaviour and regression check, not an accuracy benchmark. I calibrated thresholds on a separate development set
  (`eval/dev_queries.yaml`), and I changed no prompt, threshold or manifest entry after the run reported here.

## 2. How a question is scored

Each check compares something the system did with what the question file expects.

| Check | Passes when | Scored on |
|---|---|---|
| `category_ok` | the classifier's category is one of the expected ones | 20 questions |
| `retrieval_ok` | every expected source document is among the retrieved chunks | 15 |
| `cited_ok` | at least one expected source is cited (only checked when the outcome is "answered") | 14 |
| `outcome_ok` | the outcome (answered, abstained, declined, eligible, ineligible, needs info) is an allowed one | 20 |
| `tool_ok` | the eligibility service was called, or not called, as expected | 20 |
| `escalation_ok` | the reply was flagged for human review as expected | 2 (q02, q09) |
| `hard_gate_ok` | no `$` in any reply whose outcome forbids amounts (ineligible, needs info, tier, errors) | 20 |

A question passes (`auto_pass`) if no scored check fails. A crash or provider failure counts as an error and cannot
pass. A check that a question does not specify is not counted, which is why N differs per check.

## 3. Results

| Measure | Result |
|---|---|
| Automatic pass (`auto_pass`) | **18/20** |
| Category matches expectation | 20/20 |
| Expected sources retrieved | 15/15 |
| Expected source cited (answered questions) | 14/14 |
| Outcome as expected | 19/20 |
| Eligibility service called or not as expected | 20/20 |
| Flagged for review as expected | 1/2 |
| No dollar amount in a reply that forbids one | 20/20 |
| Errors | 0/20 |

All three eligibility questions pass, including the ineligible one and the two-turn slot-filling one. The two
no-tool traps (q04 battery add-on, q06 low-income credit) did not call the rooftop-rebate service. Both
out-of-scope questions were declined, and the terse "Error E12" query was answered, not declined.

## 4. Failures

I am reporting both failures as they are. I did not tune anything to fix them.

| Question | What the checks found | What the reply shows | Likely cause |
|---|---|---|---|
| q02: can a Community-tier member run for the board? | `escalation_ok` failed: the reply was not flagged for review | The reply says "No, Community-tier members cannot run... must be household-tier members." The documents say board seats are *elected by* Household-tier members, and say eligibility to stand varies by tier without giving the rule. The reply states an exclusion the documents do not support. | The model read "elected by Household members" (who votes) as "only Household members may stand" (who may run). Retrieval was correct. |
| q13: how many members and how much capacity now? | `outcome_ok` failed: the system abstained | The figures (just over 5,000 members, 38 MW) are in the annual report, stated as of fiscal year end. The system's recorded reason is "incomplete information". | The question says "now", the report gives year-end figures, and the composer treated the date mismatch as missing information. Abstaining is safe but unhelpful. |

Both are reasoning failures in the answer step. Retrieval found the right document in both cases, so better search
would not fix either. q02 is the more serious one: it is a confident, plausible and wrong answer, and the automatic
checks caught it only because it was not flagged for review. They cannot read the claim itself.

I would try two mitigations as separate, labelled runs: a second pass that checks each claim against the cited text
(for q02), and a prompt rule to answer with the figure and state its date scope (for q13).

## 5. What this evaluation does not show

- **Reply content is not scored.** The checks do not read the wording, figures or facts in a reply. A reply can pass
  every check and still be wrong, and q02 shows it: the wrong "No" was caught only through the missing flag.
- **I have not graded by hand.** The run folder contains `grade_sheet.csv`, ready for grading (`correct`,
  `grounded`, `notes`; rubric in `eval/RUBRIC.md`). Human feedback is needed to say how many replies are actually
  correct and grounded, so I make no accuracy claim.
- **Escalation is scored on two questions only,** so the review-flag behaviour is barely measured.
- **One run.** LLM output varies between runs even at temperature 0. I did not measure stability (`--repeat 3`) for
  this run, and I did not re-run the full-context baseline (`--mode full-context`) under these criteria.
- **Small and not blind.** See section 1.
- **Classifier confidence is self-reported** by the LLM and is not calibrated. `category_ok` checks the label only.

## 6. What I noticed in the replies (not graded)

These come from reading the saved replies, not from a check or a formal grade.

- q10 ("Error E12", a communication loss) was flagged for review as "Safety-related answer". That is cautious, not
  harmful, but it is over-flagging, and it would spend review capacity.
- q15 cites the right documents and the 30-day appeal window, but does not clearly say who makes the reversal
  decision. It passes the automatic checks, and I would expect a manual grade to mark it incomplete.
- The eligibility amounts were $2,400.00 (6 kW, q16) and $1,800.00 (4.5 kW, q18), matching the service's formula.
  The ineligible reply (q17) contained no amount.

## 7. Cost and latency

- Tokens: 39,877 in and 2,825 out over 20 questions. Estimated cost is $0.128, about **$0.0064 per question**, or
  about **$6.40 per 1,000 queries** at this question mix (a multi-turn question counts as one query).
- Latency by outcome: answered, median 3.1 s (p95 6.7 s); eligible, median 5.3 s; ineligible 4.7 s; declined 1.2 s.
  Eligibility questions cost more because they add a slot-extraction call and a next-steps call.
- Latency depends on the provider and varies between runs. In an earlier three-question run the classifier call took
  8 to 9 seconds, against 1 to 4 seconds here.

## 8. What I would do next

1. Grade the replies by hand with the rubric, ideally with a second grader, and report correct and grounded counts.
2. Re-run with `--repeat 3` to see which questions are unstable.
3. Re-run `--mode full-context` to compare the pipeline with putting the whole knowledge base in one prompt.
4. Add an LLM judge that compares each reply with the reference answer, and validate it against the manual grades.
5. Re-add wording checks where a regex is a reliable guard (for example "no gateway reset" on q09).
6. Grow the set to 100 or more questions, with expected answers written before looking at the system's replies.
7. In production, sample live replies for human review, track abstain and escalation rates, and re-run this set
   after every prompt, model or knowledge-base change.
