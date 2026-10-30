# Change control: prompts, thresholds and the language model

Owner: Lead AI & Data Science (Sajid Ali). Version 1, 2026-10-30.

**What this covers.** Any change that can alter what the copilot says:
- the prompts, which live in code: `classify.py` (classifier), `answer.py` (answers), `eligibility/slots.py` (detail
  extraction);
- the retrieval thresholds and `top_k` in `config/config.yaml`;
- the fixed reply text in `config/messages.yaml`;
- the model, its version or provider (including a move of cloud provider, which changes the model client), temperature
  and token limits;
- the embedding model.

Ordinary code changes follow the normal pull-request review; they still run the tests.

**Why it matters.** A one-word prompt edit can change how often the copilot abstains, flags or guesses. The hard
eligibility rules do not depend on prompts (they are in Python), but the wording and the grounding do. So every change
is tested against the same fixed evaluation set before it reaches members.

**Who does what.** The *author* (usually the AI/DS Associate) runs steps 1 to 3. The *reviewer* (the Lead, never the
author) checks step 3. The *approvers* in the table sign step 4. The *release owner* (backend engineer) runs steps 5 and
7. The *monitoring owner* (named in the ticket) runs step 6.

## 1. Steps

**1. Propose.** Open a ticket that states: what changes, why, what should improve, and what could get worse.
Name the files. Classify the change:

| Class | Examples | Approval |
|---|---|---|
| Minor | Typo in a message, a comment | One reviewer |
| Standard | Prompt wording, a threshold, a new model version of the same family | Reviewer and Lead |
| Major | New model or provider, new embedding model, change to the eligibility path or its fixed text | Reviewer, Lead and member-support lead |

**2. Test.** On a branch:
- `pytest -q` passes.
- Run the full evaluation: `python -m sungrid_copilot.cli eval --workers 3`. For prompt or model changes also run
  `--repeat 3`, because a single run can hide instability.
- A threshold change is calibrated on the development set (`python -m sungrid_copilot.cli calibrate`, which uses
  `eval/dev_queries.yaml`), never on the evaluation questions.
- **Model change:** add the new model's price to `pricing` in `config.yaml` (otherwise cost is not calculated;
  `check-llm` warns), and run `python -m sungrid_copilot.cli check-llm`.
- **Embedding model change:** rebuild the index (`python -m sungrid_copilot.cli ingest`) before testing. The agent
  refuses to start on an index built with another embedding model.

**3. Acceptance criteria.** Compare with the last accepted run (baseline: 18/20 on 2026-10-30, commit `f06112d`). All
of these hold, or the change is rejected or sent back:

| Measure | Required |
|---|---|
| Errors (crashes, provider failures) | 0 |
| `hard_gate_ok` (no dollar amount where forbidden) | 20/20 |
| `tool_ok` (eligibility service called or not, as expected) | 20/20 |
| Questions that passed in the baseline | None newly fails, unless the author explains each one and the Lead accepts it |
| `auto_pass` | Not below the baseline |
| Cost per query | Within 20% of the baseline, or the increase is approved |
| Latency (p95) | Not worse than the baseline by more than 25%, or approved |

Then read the saved replies for every question whose result changed, and for the eligibility questions, because the
automatic checks do not read reply content. If the change is meant to fix a failure (for example q02), say so in the
ticket and report the other questions honestly, whether they moved or not.

**4. Approve.** The approvers named in the table record the decision in the ticket: date, names, evaluation run folder
and commit. The author cannot approve their own change.

**5. Release.**
- Merge to `main`. Tag the commit (`release-YYYYMMDD-n`).
- CI builds the container image and pushes it to the registry with the tag. The model version is pinned (on Azure,
  the deployment and its model version; on Bedrock, the model id), never "latest".
- For an embedding change, build the new index alongside the old one and switch to it; keep the old one.
- Deploy to a staging copy first and run five smoke questions (one answered, one abstained, one declined, one
  eligible, one ineligible). Then deploy to production, during working hours, not on a Friday.

**6. Monitor.** For 48 hours after release, check the dashboard twice a day: abstain rate, escalation rate, guard
hits, cost per query, p95 latency and thumbs-down. Sample 20 live replies for human review in the first week. An alert
fires when any of these moves more than a set margin from the baseline week. (A guard hit means the guard did its job
and removed text; a sharp rise in guard hits is a warning that the model's behaviour changed.)

**7. Roll back.** Roll back if any of these happens: a dollar amount reaches a member in a reply that forbids one; an
error rate above 2% over an hour; abstain or escalation rate more than double the baseline for a day; or a
member-support specialist reports a harmful answer. Redeploy the previous tagged image and previous configuration (a
revert of the merge commit), and switch back to the previous index if it changed. It should take minutes, not a
rebuild. Then write a short incident note: what happened, how it was found, and which test would have caught it. Add
that test to the evaluation set.

**Urgent changes.** If a harmful answer is live, or the provider retires a model at short notice, the Lead may approve
a fix after steps 2 and 3 alone. Approvals and a full review follow within two working days. Model retirement dates
are checked monthly so that this is rare.

## 2. Release checklist

- [ ] Ticket names the change, its class and the files touched
- [ ] `pytest -q` passes
- [ ] Full evaluation run saved; `summary.md` attached to the ticket
- [ ] `--repeat 3` run done (prompt, model and embedding changes)
- [ ] Acceptance criteria table filled in, with every deviation explained
- [ ] Replies read for every question whose result changed
- [ ] Cost per query re-measured when the model or prompt length changed; new model's price added to `config.yaml`
- [ ] Thresholds changed only with development-set evidence
- [ ] Index rebuilt and old index kept (embedding changes)
- [ ] No secrets, keys or `.env` in the diff
- [ ] Approval recorded (names, date, run folder, commit)
- [ ] Commit tagged; model version pinned
- [ ] Previous image, configuration and index identified for rollback
- [ ] Staging smoke test passed (five questions)
- [ ] Monitoring owner told the release time; 48-hour check booked
- [ ] README and the architecture documents updated if behaviour changed

## 3. Records

Each change keeps: the ticket, the evaluation run folder, the approval note and the tag. The README change log gets a
dated entry for any change to behaviour, thresholds or prompts, with the reason.
