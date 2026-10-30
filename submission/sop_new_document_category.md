# SOP: Adding a new document category to the Cooperative Copilot

Owner of this procedure: Lead AI & Data Science (Sajid Ali). Version 1, 2026-10-30.

**When to use it.** A new kind of content is added to the knowledge base that does not fit the five current
categories (for example, a "Community Events" category). Adding a document to an existing category is a shorter
path: sections 3, 5, 6, 7 and 8 only.

**Why it is mostly configuration.** The category list, its descriptions and examples live in `config/categories.yaml`.
The classifier prompt, the retrieval filter and the tests read them from there, and no document id may appear in
source code (a test fails if one does). One exception: the classifier's `non_relevant` rule (`classify.py`) and the
out-of-scope messages (`config/messages.yaml`) list the topics in plain text, so both need the new topic (section 4).

## 1. Roles

| Role | Who | Responsible for |
|---|---|---|
| Requester | Anyone in SunGrid (usually member support or a programme manager) | Says why the category is needed and which documents belong in it |
| Document owner | The business owner of the content | Supplies the final text; confirms it is current and correct; names a review date |
| Category author | AI/DS Associate | Sections 3 to 6 |
| Reviewer | The Lead, or a second engineer | Section 7 |
| Approver | Lead AI & Data Science, with the member-support lead for anything member-facing | Signs off in section 8 |
| Release owner | Backend engineer | Release in section 8 |

The author and the reviewer must be different people.

## 2. Decide that a new category is needed

*Owner: requester, decided by the Lead.* Write three lines in the change ticket: what members will ask, which documents
answer it, and why none of the existing categories fits. If two or fewer short documents are involved, prefer an
existing category. Every category adds to the classifier prompt and gives the classifier one more way to be wrong.

## 3. Receive and prepare the documents

*Owner: document owner, then category author.*
- The document owner supplies the final text as Markdown: one `#` title and `##` sections, one topic per section
  (the index splits documents on `##` headings). No personal data.
- Check the text does not contradict existing documents (for example, deadlines or fees stated differently). If it
  does, list the conflict in the ticket. A conflict is resolved by the owners, not by the model.
- Put the files in `docs/` and add each one to `config/doc_manifest.yaml`: `primary` category, `secondary` only if it
  truly belongs in two (as document 06 does; add a line to `ambiguity_note.md`), `owner`, and the review date in `note`.

## 4. Configure the category

*Owner: category author.*
- Add one entry to `config/categories.yaml`: a `name` in lower_snake_case, a `display_name`, a one-sentence
  `description`, and 5 or more `examples` in real member wording, including one terse query (such as "Error E12").
  Do not copy sentences from the documents.
- Add the new topic to the topic list in the classifier's `non_relevant` rule (`classify.py`) and in `out_of_scope`
  and `empty_message` (`config/messages.yaml`). Otherwise questions on the new topic may be declined as off-topic.
  This is a prompt change, so it is also covered by `change_control_prompt_and_model.md`.

## 5. Validation checks (all must pass)

*Owner: category author.*
1. **Ingestion:** `python -m sungrid_copilot.cli ingest`. Every new document produces chunks, and the chunk count
   matches its `##` sections.
2. **Unit tests:** `pytest -q` passes. This includes the tests that the manifest matches the files in `docs/`, that
   every category is known, and that no document id appears in source code.
3. **Classifier check on the development set:** add at least 8 new queries for the category (including 2 terse and 2
   borderline ones) to `eval/dev_queries.yaml`, never to the evaluation set. Run
   `python -m sungrid_copilot.cli calibrate`. The classifier must pick the new category for most of them, and the
   existing queries must not lose accuracy.
4. **Retrieval check:** for each new query, `python -m sungrid_copilot.cli retrieve "<query>"` must show the right
   document among the top 5 chunks.
5. **Neighbour check:** run `retrieve` on 5 existing development queries from neighbouring categories and confirm
   they still land in their old categories.
6. **Thresholds:** if the confidence or decline thresholds need to change, follow
   `change_control_prompt_and_model.md`. Do not edit thresholds inside this procedure.

## 6. Update the evaluation set

*Owner: category author.*
- Add at least **3 questions** to `eval/questions.yaml` for the new category: one plain fact, one that needs two
  passages or documents, and one the documents cannot answer (the correct reply is to abstain and flag for review).
- Write the expected sources and outcomes **before** looking at the system's replies, and add the purpose comment
  (`TESTS` and `PASS MEANS`) that every question carries.
- If the category touches money, deadlines or safety, add one question for that risk.
- The set is capped at 20 questions by a test, and it is full. Retire the weakest existing questions, or raise the
  cap with the Lead's agreement. A test also checks that every category has at least one question.
- Run the full evaluation (`python -m sungrid_copilot.cli eval --workers 3`). Compare it with the last accepted run:
  no existing question may newly fail, and the pass rate must not fall. Keep the output folder and `summary.md` with
  the ticket.

## 7. Review

*Owner: reviewer.* The reviewer checks the diff (categories, manifest, topic wording, new queries, new questions),
the evaluation summary, and that no secrets, keys or `.env` files are in the change. The reviewer also reads the
saved replies for the new questions, because the automatic checks do not read reply content.

## 8. Sign-off and release

*Owner: approver, then release owner.* Sign-off needs: the document owner confirms the content, the reviewer approves
the diff and results, and the approver records the decision in the ticket (date, names, evaluation run folder,
commit). The release owner then follows `change_control_prompt_and_model.md`: tag the commit, rebuild the index in
staging, run five smoke questions, then release to production. Keep the previous tag and index: rollback means
reverting the merge commit and rebuilding the index from it.

## 9. After release

*Owner: category author, with the Lead.* Watch the new category for two weeks. For the first week, sample 10 live
replies a day for human review. Track the abstain rate, the escalation rate and member thumbs-down for the new
category. If the abstain rate is clearly above the other categories, the documents are probably incomplete, so tell
the document owner.
