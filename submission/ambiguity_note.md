# Ambiguity note: document 06 (rebate reversals and billing adjustments)

## The problem

Document `06_ambiguous_rebate_billing_adjustments` covers one situation that belongs to two categories. A rebate is
reversed (Incentive & Rebate), and the money is recovered through a billing adjustment on the member's bill
(Billing & Account). A member can reach it from either side: "Why is there an extra charge on my bill?" or "My rebate
was reversed, how long do I have to appeal?".

If the system forces the document into one category, half of the questions about it will miss it.

## What I did

1. **The manifest records a primary and an optional secondary category per document.** Document 06 is primary
   `incentive_rebate` and secondary `billing_account` (`config/doc_manifest.yaml`). Nothing in code mentions the
   document by name; a test fails if a document id appears in the source.
2. **The category is a retrieval filter, not a router.** The classifier proposes a category. Search is filtered to
   documents whose primary OR secondary category matches. The filter narrows the search; it never decides which
   pipeline runs.
3. **A margin-based fallback protects against a wrong category.** Retrieval also runs unfiltered. If the unfiltered
   best match scores more than 0.04 higher than the filtered best match, the unfiltered results are used. The same
   fallback applies when the classifier's confidence is below 0.6.
4. **The decline path is guarded, not just classified.** `non_relevant` declines a question only if the classifier
   is at least 0.85 confident AND the best unfiltered retrieval score is below 0.60. Retrieval scores alone overlap
   between in-scope and out-of-scope questions, so neither signal is trusted by itself.

## Alternatives I rejected

| Option | Why not |
|---|---|
| One category per document | Forces a wrong answer for half the queries that touch document 06. |
| Copy the document into both categories | Two copies drift apart; an edit to one is silently missing from the other. |
| No category filter at all | Works at 14 documents, but gives up the narrowing that matters as the knowledge base grows. |
| Special-case document 06 in code | Does not generalise: the next ambiguous document needs a code change. |

## Evidence

Two evaluation questions are tagged `ambiguous_doc` (q14 from the billing side, q15 from the rebate side). Both retrieve
document 06 and pass every automated check, in all three repeats (`eval_report.md`).

## Limits

- Two questions show the mechanism works; they do not measure how often it fails. The set is small.
- The classifier's confidence is self-reported by the model and is not calibrated. The thresholds were set on a
  separate development set, not on the evaluation questions.
- The categories for documents 07 to 14 are my assumption: the starter kit labels only the first six. They are
  recorded in the manifest and are easy to change.
- Retrieving document 06 does not guarantee a complete answer. The pipeline's answer to q15 did not say who makes the
  reversal decision, and the first hand grading marked it incomplete (see `eval_report.md`).
- Adding a new ambiguous document is a manifest edit plus an evaluation question, not a code change
  (`sop_new_document_category.md`).
