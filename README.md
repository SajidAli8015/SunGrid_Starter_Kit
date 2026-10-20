# SunGrid Cooperative Copilot

Prototype Copilot that answers SunGrid member questions from the knowledge base in `docs/`
(retrieval-augmented generation) and calls the eligibility service in `stub_tools.py` for
Rooftop Rebate questions. Work in progress: so far only the scaffold, configuration and the
provider-agnostic LLM layer exist.

## Setup

Requires Python 3.10+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
copy .env.example .env          # macOS/Linux: cp .env.example .env, then fill in your values
```

## Check the LLM connection

```
python -m sungrid_copilot.cli check-llm
```

Prints the provider, model/deployment, endpoint host and whether the API key is set (never the
key itself), then makes one plain call and one JSON call. Set `LLM_PROVIDER=fake` to run it
offline.

Providers: `azure_openai`, `openai`, `anthropic`, `gemini`, `fake`. **Only Azure OpenAI is
tested end to end**; the other clients are written against their SDKs but unverified.

## Build the index and inspect retrieval

```
python -m sungrid_copilot.cli ingest
python -m sungrid_copilot.cli search "How long do I have to appeal a rebate decision?"
python -m sungrid_copilot.cli search "extra charge after my rebate" --category billing_account --top-k 3
python -m sungrid_copilot.cli search "battery incentive" --json
```

`ingest` reads `config/doc_manifest.yaml`, chunks each doc in `docs/` by `##` section, embeds
locally with fastembed (`BAAI/bge-small-en-v1.5`, downloaded on first run, no PyTorch) and
rebuilds a Chroma index in `.chroma/`. `search` is raw vector search with no LLM call; it fails
with a clear message if the index is missing or was built with a different embedding model.

## Classify, retrieve and calibrate

```
python -m sungrid_copilot.cli classify "My inverter shows E07"
python -m sungrid_copilot.cli retrieve "How long do I have to appeal a rebate decision?" --force-category program_policies
python -m sungrid_copilot.cli calibrate
```

`classify` makes one LLM call (cached in `.cache/classify/`, `--no-cache` to bypass). Categories,
their descriptions and examples come from `config/categories.yaml`. `retrieve` adds the
category-filtered search with a margin-based fallback to unfiltered search, and prints why it
chose what it did and whether the guarded `non_relevant` decline would apply. `calibrate` runs the
development set in `eval/dev_queries.yaml` and suggests `fallback_margin` and
`non_relevant_score_ceiling`; it never edits the config. Its full report goes to
`eval/results/calibration.json`.

## Ask the Copilot

```
python -m sungrid_copilot.cli ask                       # interactive; type exit to quit
python -m sungrid_copilot.cli ask --once "E07" --debug  # one message, with the trace
```

Each message is classified, retrieved, then either answered from the knowledge base with sources
(or abstained and flagged), declined if clearly out of scope, or routed to the Rooftop Rebate
eligibility flow, which asks for missing details across turns and calls the eligibility service
once. Escalated replies end with "Flagged for human review". Every message appends one line to
`logs/queries.jsonl` with outcome, retrieval, tokens and latency, and a hash of the text (never
the text or any slot values).

## Tests

```
pytest
```

Tests use the `fake` provider and never touch the network.

---

## Starter kit (original README)

This is a synthetic scenario. "SunGrid Cooperative" is fictional; any resemblance
to a real company is coincidental. The full task brief is in the accompanying
PDF/Word document sent to you by email — this README covers only the materials
in this kit.

## What's in this kit

```
docs/
  01_program_policies.md
  02_incentive_rebate_programs.md
  03_billing_faqs.md
  04_technical_installation_guidance.md
  05_company_updates.md
  06_ambiguous_rebate_billing_adjustments.md
  07_installer_certification.md
  08_governance_voting.md
  09_battery_storage_incentive.md
  10_low_income_bill_credit.md
  11_net_metering_trueup.md
  12_autopay_failure_policy.md
  13_battery_storage_installation.md
  14_annual_impact_report.md
stub_tools.py
README.md   <- this file
```

- `docs/` — a small internal knowledge base for SunGrid Cooperative (14 documents
  spanning program policies, incentive/rebate programs, billing & account,
  technical/installation guidance, and company updates). One document (`06_...`)
  is deliberately ambiguous — it doesn't sit cleanly under a single category.
  How you handle that is part of what's assessed.
- `stub_tools.py` — a mock eligibility-check function representing a
  downstream service. Wire it into your agent as a tool call; don't
  reimplement its logic elsewhere.

You are free to add more synthetic documents or synthetic user queries of your
own if useful for testing, as long as the ones provided remain the core test set.

