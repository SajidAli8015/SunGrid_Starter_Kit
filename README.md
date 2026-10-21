# SunGrid Cooperative Copilot

A prototype assistant that answers SunGrid Cooperative member questions from a 14-document knowledge base
(`docs/`). Answers are grounded in retrieved sections and cite them; if the sections do not support an answer,
it abstains and flags the question for a person. Questions about whether a member qualifies for the Rooftop
Rebate go to a separate eligibility service (`stub_tools.py`, treated as owned by another team), and the result
is enforced in Python: an ineligible member never sees an amount, and any LLM-written text that adds one is
dropped. SunGrid Cooperative is fictional and all documents are synthetic.

## Architecture

1. **Classify** the message (one LLM call): category, self-reported confidence, and whether it asks about the
   member's own Rooftop Rebate eligibility. Categories come from `config/categories.yaml`.
2. **Retrieve** (local, no LLM): an unfiltered and a category-filtered vector search. The filter is used only if
   the label is confident and the filtered top result is within `fallback_margin` of the unfiltered one;
   otherwise the unfiltered results are used and the reason is recorded.
3. **Decline guard**: the only early exit. It needs both a confident `non_relevant` label and a weak unfiltered
   top score (`non_relevant_score_ceiling`), so terse in-scope queries such as "E07" are not refused.
4. **Eligibility path** (Rooftop Rebate only): extract slots (LLM), ask one combined question for anything
   missing, refuse to check a non-Household tier, validate inputs, call the service once, and map its result
   through a pure-Python gate. The reply is fixed text from `config/messages.yaml`; KB "what happens next" text
   is appended only if an output guard finds no amount other than the service's.
   **Otherwise, a grounded answer**: the composer may use only the numbered chunks, must cite them, and code
   rejects unknown or missing citations (one retry, then abstain).
5. **Log** one JSON line per message to `logs/queries.jsonl`: outcome, retrieval, service call, tokens,
   latency per step, estimated cost.

```
config/            config.yaml (settings, thresholds, pricing), categories.yaml, messages.yaml, doc_manifest.yaml
docs/              the knowledge base (14 markdown files, unchanged from the kit)
eval/              questions.yaml (held-out set), dev_queries.yaml (tuning only), RUBRIC.md, README.md
scripts/           clean_clone_check.py
src/sungrid_copilot/
  agent.py         the bounded flow above
  answer.py        grounded answer composer with citation checks
  classify.py      classifier (prompt built from categories.yaml)
  retrieval.py     filter + margin fallback, decline guard
  calibrate.py     threshold tuning on the dev set
  eligibility/     slots, adapter (only caller of the service), gate, flow, render, guard
  evaluation/      eval harness, report, full-context baseline
  kb/              manifest, chunking, embeddings, Chroma store, ingestion
  llm/             provider clients (the only provider-specific code), fake client for tests
  cli.py, config.py, messages.py, querylog.py, usage.py, cache.py, categories.py
stub_tools.py      the eligibility service stand-in (unchanged)
submission/        assessment deliverables (separate from docs/, the knowledge base)
tests/             offline tests (no network, no keys)
```

## Requirements

- Python 3.10 or newer.
- Internet access on the first run: the pip packages (about 550 MB installed in the venv) and the embedding
  model (`BAAI/bge-small-en-v1.5`, ONNX, about 65 MB), which fastembed downloads once into its cache. No PyTorch.
- A key for one LLM provider. Tests need no key.

## Install

Windows PowerShell:

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

macOS / Linux:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Run commands from the repository root: the eligibility service module is loaded from there by name.

## Configure

Copy `.env.example` to `.env` (git-ignored; Windows: `copy .env.example .env`) and fill in one provider block.
`LLM_PROVIDER` selects the provider and overrides `llm.provider` in `config/config.yaml`.

| `LLM_PROVIDER` | Environment variables | Status |
|---|---|---|
| `azure_openai` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, optional `AZURE_OPENAI_API_VERSION` | tested end to end (gpt-4o) |
| `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` | implemented, unit-tested with fakes, not verified live |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | implemented, unit-tested with fakes, not verified live |
| `gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` | implemented, unit-tested with fakes, not verified live |
| `fake` | none | offline scripted client for tests and smoke checks |

Azure notes:
- `AZURE_OPENAI_ENDPOINT` may be the resource root (`https://<resource>.openai.azure.com/`) or a full request URL
  copied from the portal; it is reduced to `scheme://host/`.
- API version: `AZURE_OPENAI_API_VERSION` wins, then an `api-version` in the endpoint URL, then `2024-02-01`.
- The deployment name is used as the model.

Non-secret settings live in `config/`: `config.yaml` (provider, per-role model overrides, timeouts, retrieval
and classifier thresholds, logging, pricing per 1M tokens), `messages.yaml` (all fixed member-facing text),
`categories.yaml` (category names, descriptions, examples) and `doc_manifest.yaml` (per-document title,
categories, owner).

## Run

```
python -m sungrid_copilot.cli check-llm        # provider, model, endpoint host, key set/MISSING, one test call
python -m sungrid_copilot.cli ingest           # chunk docs/, embed locally, rebuild .chroma/
python -m sungrid_copilot.cli search "How long do I have to appeal a rebate decision?" --top-k 3
python -m sungrid_copilot.cli classify "My inverter shows E07"
python -m sungrid_copilot.cli retrieve "How long do I have to appeal a rebate decision?" --force-category program_policies
python -m sungrid_copilot.cli eligibility --zip 94101 --income 85000 --size-kw 7.5 --installer-approved yes --tier household
python -m sungrid_copilot.cli ask              # interactive session; type exit to quit
python -m sungrid_copilot.cli ask --once "E07" --debug
```

`search`, `ingest` and `eligibility` make no LLM calls. `eligibility` runs the deterministic flow from explicit
values; omit an option to see the clarifying question. `--debug` on `ask` prints the trace: category,
confidence, fallback reason, margin, chunks and scores, whether the service was called, the gate verdict, guard
violations, tokens and latency per step. Escalated replies end with "Flagged for human review: <reason>".
Other commands: `calibrate` (dev-set threshold tuning) and `extract-slots`.

## Evaluate

```
python -m sungrid_copilot.cli eval --workers 3
python -m sungrid_copilot.cli eval --repeat 3
python -m sungrid_copilot.cli eval --mode full-context
python -m sungrid_copilot.cli eval-summarize eval/results/<run> --grades <filled_grade_sheet.csv>
```

Each run writes `results.json`, `summary.md` (counts `n/N`, failing questions, latency, tokens, cost) and
`grade_sheet.csv` to `eval/results/<UTC time>/` (git-ignored). Fill the grade sheet with
[eval/RUBRIC.md](eval/RUBRIC.md), then merge it with `eval-summarize`. `--repeat N` reports which questions are
unstable; `--mode full-context` is a baseline that sends the whole knowledge base to the composer in one prompt.
See [eval/README.md](eval/README.md).

## Tests

```
pytest
```

Offline and keyless: the fake LLM, a hash embedder and a temporary Chroma store, plus the real stub. Includes
checks that no secrets, doc file names or doc IDs appear in code, and that retrieval and eligibility do not
import each other.

## Assumptions

- The kit labels only docs 01-05 (and 06 as ambiguous). Categories for docs 07-14 are our assumption, recorded in
  `config/doc_manifest.yaml`. Owners other than the Incentive Program committee and the Billing team (the only
  teams the documents name) are placeholders.
- Doc 06 (rebate refund and billing adjustment) is tagged primary `incentive_rebate`, secondary
  `billing_account`: the Incentive Program committee makes the reversal determination and the Billing team
  executes the schedule, so billing-worded questions must still find it. See
  [submission/ambiguity_note.md](submission/ambiguity_note.md).
- The eligibility service belongs to another team. `stub_tools.py` is unchanged and is called only through
  `eligibility/adapter.py`; its logic is not reimplemented.
- The service covers only the Rooftop Rebate. Battery Storage Add-On and Low-Income Bill Credit questions are
  answered from the documents and never call it.
- Member tier is a precondition checked before the call: a non-Household tier gets no check and is flagged
  for review (the tier-transfer wording in the documents is ambiguous).
- The service reports only the first failing condition, so an ineligible reply never says "the only issue is".
- An eligible result is a preliminary check, not a determination; the reply says funding and documentation
  requirements apply and the committee decides.
- The held-out evaluation set was written after the first demo runs, so it is not blind.

## Known limitations

- The eligibility service is called once with a timeout and no retries; failures escalate to a person.
- The output guard catches `$500`, `USD 500` and `500 dollars` anywhere in the reply. In the LLM-written part of
  a non-eligible reply it also flags bare amounts such as `4,000`, `4000`, `3k` and `40 cents per watt`. That
  check fails safe: a year or a 3-digit figure in the next-steps text drops that text. Amounts written in words
  ("three thousand dollars") are not caught.
- Classifier confidence is self-reported by the LLM and uncalibrated; it only widens search, except in the
  guarded decline.
- Known wrong answer: "Can a Community-tier member run for the board?" is answered with a flat "no" that the
  documents do not support (they never say which tiers may stand), and is not escalated (eval q02).
- Over-abstention on time-qualified questions: "How many members does SunGrid have now?" abstains although the
  annual report figures were retrieved (eval q13).
- The category filter compares top-1 scores only, so a multi-document question can lose one source.
- Only Azure OpenAI has been verified against a live service.
- The vector store (`.chroma/`) and LLM caches (`.cache/`) are local and single-user; usage tracking is
  per-process and not thread-safe for concurrent requests.
- The evaluation set is small (20 questions); results are counts, not rates.

More detail, with reasons, in [NOTES.md](NOTES.md).

## Privacy and security

- No keys in the repository: secrets come from environment variables or a git-ignored `.env`, settings objects
  mask them, and a test scans the repo for key-like assignments.
- `logs/queries.jsonl` stores a SHA-256 hash and the length of each question, never its text, ZIP, income or any
  other slot value, unless `logging.include_query_text` is set to true for local debugging.
- LLM caches store the member's text, so they are off for member sessions (`ask` and `eval`); only the tuning
  commands (`classify`, `calibrate`, `extract-slots`) cache.
- Sessions live in memory only.

## AI assistance

The code was written with an AI coding assistant (Claude Code) working under a written rules file
(`CLAUDE.md`), and reviewed and tested by the author. Shortcuts and limitations were logged as they arose in
`NOTES.md`.

## Submission documents

See [submission/README.md](submission/README.md).
