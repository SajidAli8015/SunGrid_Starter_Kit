# CLAUDE.md: SunGrid Cooperative Copilot

## What this is
A take-home assessment for a Lead AI & Data Science role. We are building a prototype Copilot that
answers SunGrid member questions from 14 synthetic knowledge-base documents (RAG) and calls a separate
eligibility service (`stub_tools.py`) for rooftop-rebate eligibility questions.

Part of the grade is judgement. Simple, correct, tested and honestly evaluated beats clever.
Do not gold-plate. The repo will be read by reviewers, and the author will later review it as if a junior
colleague wrote it, so keep it clean and explainable.

## Hard rules (never violate)
1. Never edit `stub_tools.py`. Call it only through `eligibility/adapter.py`.
2. No secrets in the repo. Keys come from environment variables / a git-ignored `.env`. Never print, log,
   echo, `cat` or commit a key. Never read the contents of `.env`; you may check that a variable is set.
3. The eligibility hard gate is enforced in Python (`eligibility/gate.py`), not in a prompt. If the tool
   returns `eligible=False`, the user-facing text is built from the tool's `reason` only: no amount, no
   estimate, no "you would normally get". The LLM must never see `estimated_rebate_usd` unless eligible=True.
4. No document file names or doc IDs in source code. Doc-specific facts live only in
   `config/doc_manifest.yaml`.
5. The query category is a retrieval filter, not a router. The only early exit is a *confident*
   `non_relevant` decline.
6. Provider-specific code lives only in `src/sungrid_copilot/llm/`. Everything else uses `LLMClient`.
7. Answers must be grounded in retrieved chunks and cite their sources. If the chunks do not support an
   answer, abstain and say so. Never fill gaps from general knowledge.
8. No agent frameworks (LangChain, LlamaIndex, LangGraph, etc.). No new dependencies without asking.
9. Cross-platform: use `pathlib`, no bash-only scripts, assume the author may be on Windows.

## Architecture: LLM chooses, code enforces
```
query
 1. classify -> {category, confidence, needs_eligibility_check}   (1 LLM call, JSON validated by Pydantic)
 2. category == non_relevant AND confidence >= NON_RELEVANT_MIN_CONF -> polite decline, log, stop
 3. retrieve top-k, filter: category IN (chunk.primary, chunk.secondary)
      fallback to UNFILTERED search if classifier confidence < CLASSIFIER_MIN_CONF or best score < MIN_SCORE
      a low-confidence non_relevant label is treated as "unknown category": search unfiltered
 4. needs_eligibility_check -> eligibility flow (below)
    else -> compose grounded answer with citations, or abstain
 5. append one JSONL record to logs/queries.jsonl
```
Categories (snake_case enum): `program_policies`, `incentive_rebate`, `billing_account`,
`technical_installation`, `company_updates`, `non_relevant`.

### Eligibility flow
- Scope: the stub only covers the Rooftop Rebate. For the battery incentive or the low-income credit,
  answer from the docs and do NOT call the tool.
- Slots (LLM extraction -> Pydantic): `household_zip`, `annual_income_usd` (adjusted gross income),
  `system_size_kw`, `installer_approved` (bool; the installer was on the approved list at the time of
  installation, certification not lapsed), `member_tier`.
- Any missing slot -> ask ONE clarifying question naming what is missing. Never guess or default.
- `member_tier != household` -> do not call the tool. Explain from the docs that the rebate is for
  Household-tier members and flag for human review (tier-transfer wording in the KB is ambiguous).
- The adapter validates and normalises inputs (strict bool, 5-digit ZIP string, finite non-negative
  income, finite positive size), applies a timeout, and turns any exception into a typed `ToolError`.
- The gate (pure function) maps the result to `INELIGIBLE | ELIGIBLE_PRELIMINARY | TOOL_ERROR`.
  It also rejects malformed results (non-bool `eligible`, `eligible=False` with amount > 0).
- The service returns only the FIRST failing check. Never say "the only issue is X". Say that at least
  this check failed and that other checks were not evaluated.
- ELIGIBLE_PRELIMINARY is a pre-check, not a formal determination: mention funding/waitlist and
  documentation requirements from the KB. Amounts are inserted from the structured result, and a
  post-check verifies the final text contains no amount other than the tool's.
- TOOL_ERROR or malformed result -> no answer about eligibility, escalate to a human.

## Ingestion and retrieval
- `config/doc_manifest.yaml`: per doc `file`, `title`, `primary`, `secondary` (list), `owner`, `note`.
- Chunk by `##` section. Embedding text = `"{doc title} > {section heading}\n{body}"` (headings such as
  "Eligibility" repeat across docs). Chunk metadata: doc_id, title, section, primary, secondary,
  source_path, content_hash, ingested_at.
- Embeddings: local sentence-transformers (default `BAAI/bge-small-en-v1.5`, configurable), independent of
  the chat provider. Store the embedding model name in the index; on mismatch fail loudly and say to re-ingest.
- Vector store: Chroma persistent in `.chroma/` (git-ignored). Ingestion is idempotent and rebuilds cleanly.

## Config
- Non-secret settings: `config/config.yaml` (provider, models, top_k, thresholds, timeouts).
- Secrets and provider selection: environment variables, documented in `.env.example` (placeholders only).
- `LLM_PROVIDER` = `azure_openai` | `openai` | `anthropic` | `gemini` | `fake`.
- Azure: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`.
- Only Azure is tested end to end. Say so in the README; do not claim the others are verified.

## Logging
One JSONL record per query: timestamp, query, category, confidence, retrieved ids + scores, fallback used,
tool called, gate verdict, escalated, tokens in/out, latency, estimated cost. This feeds the cost-per-1,000
number and the monitoring section of the design record.

## Evaluation
`eval/questions.yaml` (15-20 questions) + `eval/run_eval.py`. Automated checks: category match, expected
source in top-k, tool called or not, gate outcome, must-not-contain. Answer quality is hand-graded from a
generated CSV. Report counts (for example 15/18), not percentages. Failures are included, never hidden.

## Working agreements
- Plan briefly before large changes. Run the tests after each task. Make small, focused commits.
- Tests never touch the network: use the `fake` LLM provider.
- When you cut a corner or notice a limitation, append one line to `NOTES.md` (what + why). This feeds the
  design record and the code-review document.
- If blocked or if the brief is ambiguous, stop and ask. Do not invent requirements.
