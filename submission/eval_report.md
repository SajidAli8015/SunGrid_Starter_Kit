# Evaluation report

All figures are counts of questions (n/N), not rates. The sample is small and the numbers are indicative, not
statistically meaningful.

## 1. The evaluation set

- 20 held-out questions in `eval/questions.yaml`: 15 knowledge questions covering all five categories, 3 eligibility
  questions (eligible, ineligible, multi-turn slot filling) and 2 out-of-scope questions.
- It includes the traps the brief names: two questions that depend on document 06, a terse fault-code query that must
  not be declined, a question whose answer is not in the knowledge base, an arithmetic cap, and a time-qualified
  statistic.
- **Provenance:** the set was written after the first end-to-end demo runs, so it is not blind. Three questions are
  tagged `seen_in_demo` because they closely mirror a demo query. Thresholds were calibrated on a separate development
  set (`eval/dev_queries.yaml`), and no prompt, threshold or manifest entry was changed after the first run on this
  set.
- **Two kinds of scoring.** Ten automated checks (category, retrieval, citation, outcome, tool use, escalation,
  required and forbidden text, and the dollar-amount hard gate) are coarse regex proxies. Each answer was then graded
  by hand against a reference answer on two points: `correct` and `grounded` (`eval/RUBRIC.md`). I did the manual
  grading myself, for both the pipeline run and the full-context run, as a single grader; there was no second grader.
  The reasons for every score of 0 are in section 2.

## 2. Results: the pipeline

| Measure | Result |
|---|---|
| Automated pass (`auto_pass`) | 18/20 |
| Same outcome and same `auto_pass` across 3 repeats | 20/20 |
| Category matches expectation | 20/20 |
| Expected sources retrieved | 15/15 |
| Dollar-amount hard gate held | 20/20 |
| Hand-graded correct | 17/20 |
| Hand-graded grounded | 16/17 |
| Errors | 0/20 |

### Failures (reported, not fixed)

| Question | What happened | Likely cause | Mitigation |
|---|---|---|---|
| q02 (can a Community-tier member run for the board?) | Said a flat "No, only Household-tier members…". The knowledge base does not say which tiers may stand. Not escalated. | The model inferred an exclusion from a related rule (who votes). Retrieval was correct. | A second pass that checks each claim against the cited text. One extra call. |
| q13 (members and installed capacity) | Abstained, although the figures (just over 5,000 members, 38 MW) are in the annual report. | The report states the figures as of fiscal year end; the question asks about "now". The composer treated the mismatch as missing information. | A prompt rule: answer with the figure and state its date scope. |
| q15 (who decides, how long to appeal, where) | Automated checks pass. Hand grading: incomplete, because the answer does not say who makes the reversal decision. | Retrieved the right documents; the composer did not state the decision maker. | Same claim-checking pass, with a completeness check against the question. |

q02 is the most important. It is a confident, plausible and wrong answer, and it passes every check except
escalation. The hand grading caught it; the regexes could not.

### Why each question was graded 0

How I scored: `correct` = the key facts match the reference answer and nothing contradicts the knowledge base. For an
abstention, correct means the behaviour matches the reference. `grounded` = every claim is supported by a cited
source. A score of 1 means I found the reference's key facts in the answer and no unsupported claim.

| Run | Question | correct | grounded | Reason |
|---|---|---|---|---|
| Pipeline | q02 | 0 | 0 | The answer states as fact that only Household-tier members may stand. The knowledge base says only that board seats are elected by Household-tier members and that candidates need 12 months in good standing; the policies document says eligibility varies by tier without saying how. The exclusion is therefore not supported by the cited text, so grounded is 0 too. The reference behaviour is to say it is not specified, give what is stated, and flag for review; the answer was not escalated. |
| Pipeline | q13 | 0 | n/a | The figures are in the annual report, and the reference expects them with the note that they are as of fiscal year end. The system abstained instead, so the behaviour does not match the reference. Grounded does not apply to an abstention. |
| Pipeline | q15 | 0 | 1 | The question has three parts: who decides, how long to appeal, where to appeal. The answer gave the second and third correctly and never named who makes the decision. Correct is 0 because a required part is missing. Grounded is 1 because what it did say is supported by the cited text. |
| Full-context | q02 | 0 | 0 | The same unsupported "only Household-tier members" claim, for the same reasons as above. |
| Full-context | q06 | 0 | n/a | It abstained. The knowledge base gives the threshold as 200% of the regional low-income threshold (without a dollar value), and the reference expects that fact. An abstention here is safe but not the expected behaviour. |

q13 in the full-context run was graded correct: the figures match the reference. It does not say the figures are as
of fiscal year end, which I counted as a minor omission rather than an error.

## 3. Baseline: all documents in one prompt

To test whether retrieval earns its place, the same composer was run with all 69 chunks in one prompt (about 5,000
input tokens), with no classifier, filter or search. It can only run the 15 knowledge questions.

| Measure (same 15 questions) | Pipeline | Full-context |
|---|---|---|
| Hand-graded correct | 12/15 | 13/15 |
| Failed by hand | q02, q13, q15 | q02, q06 |
| Input tokens per question | ~1,900 | ~4,950 |
| LLM calls per question | 2 | 1 |
| Cost per 1,000 queries (gpt-4o, Global Standard list price) | ~$6.1 | ~$13.3 |
| Median latency | 3.5 to 3.8 s | 1.65 s |

What this shows:

- **Accuracy is a tie at this size.** One question of difference is noise at n=15.
- **q02 fails in both modes**, so it is a reasoning failure, not a retrieval failure. Better search would not fix it.
- **Over-abstention moves between questions** (q13 in the pipeline, q06 in full-context). That points at the
  composer prompt, not at retrieval.
- **Full-context is faster today** because it skips the classifier call. The latency figures are not like for like:
  the pipeline's covers the whole turn, full-context's covers LLM time only.
- **The pipeline costs about 2.2 times less today, and the gap grows with the knowledge base.** Full-context input
  grows with the corpus. At ten times the documents it would be about 50,000 tokens per query (roughly $125 per 1,000
  queries, assuming the same chunk size); at one hundred times it no longer fits in the context window. The
  pipeline's per-query input stays flat.
- So retrieval is justified here by cost at scale, a hard context limit, and sending the model only the sections a
  question needs. It is not justified by accuracy or latency at 69 chunks.
- Prompt caching of the fixed full-context prefix could narrow the cost gap. I have not verified the caching terms
  for this deployment.

## 4. Cost and latency (pipeline, all 20 questions)

| Outcome | n | Median latency | Mean LLM calls | Mean tokens in |
|---|---|---|---|---|
| Answered | 14 | 4.0 s | 2.0 | 1,893 |
| Abstained | 1 | 3.1 s | 2.0 | 1,806 |
| Declined out of scope | 2 | 2.4 s | 1.0 | 912 |
| Eligibility, eligible | 2 | 15.3 s | 3.5 | 2,905 |
| Eligibility, ineligible | 1 | 15.6 s | 3.0 | 2,610 |

- Total over 20 questions: 38,553 tokens in, 2,886 out; $0.1252 total, $6.26 per 1,000 queries (gpt-4o 2024-11-20 at
  $2.50 / $10.00 per million tokens, Global Standard).
- The classifier is about half of the pipeline's input tokens and one of its two sequential calls.
- Eligibility takes about 15 s and needs 3 to 3.5 calls (classify, extract slots, the service, then a next-steps
  answer). That is too slow for a chat experience, and it is the first thing to reduce (section 5).
- Latency on Azure varied between runs: earlier demo runs were slower. Treat these as rough.

### How cost and latency were measured

- **Cost:** the harness records input and output tokens for every LLM call. Cost is those tokens multiplied by the
  list prices in `config/config.yaml`: $2.50 input and $10.00 output per million tokens for gpt-4o 2024-11-20, Global
  Standard deployment. I took the prices from a third-party price page and have not yet checked them against
  Microsoft's pricing page; other deployment types cost slightly more.
- **Projection:** mean cost per question times 1,000, at the mix of questions in this set (a multi-turn question counts
  as one query). A different mix of eligibility and plain questions would change it, because eligibility questions use
  more calls.
- **Not included:** embeddings (computed locally, no charge), hosting, the vector store, retries, and any cost of the
  real eligibility service.
- **Latency:** wall-clock time per question as measured by the evaluation harness, from the question being handed to
  the agent until the reply is returned. For the pipeline this covers the classifier, retrieval, the eligibility
  service and the composer. For the full-context run it is the sum of the LLM call times only, so the two are not
  strictly comparable.
- **Conditions:** three questions ran in parallel, LLM caches were off, and a single Azure deployment was called over
  the public internet from one machine. This is not a load test. The first question each worker ran was consistently
  slow (10 to 13 s), which I believe is first-call warm-up but have not confirmed.
- **Repeats:** the 3-repeat run shows the same outcomes every time; its latency and cost figures are means of the
  three runs.

## 5. What I would do next

1. Add a claim-checking pass for q02 and q15 (one extra call), then re-run on a fresh question set, not this one.
2. Add the prompt rule for time-qualified answers (q13).
3. Cut latency: run classification in parallel with the unfiltered search (already needed for the fallback), use a
   smaller model for the classifier, and merge classification with slot extraction.
4. Grow the evaluation set to 100 or more questions with a second grader, and write the answers before looking at
   system output.
5. Test the other providers against a live key. Only Azure OpenAI was verified end to end; the others are implemented
   and unit-tested with fakes.

## 6. Limitations

- Small n, a set that is not blind, and a single grader.
- Regexes are a coarse proxy for correctness; hand grading disagreed with them on q15.
- The classifier's confidence is self-reported and not calibrated.
- The output guard cannot detect dollar amounts written in words.
- Every eligibility result comes from a stub; the real service's behaviour, latency and failure modes are unknown.
