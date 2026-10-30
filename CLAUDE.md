# CLAUDE.md: SunGrid Cooperative Copilot

## What this is
A take-home assessment for a Lead AI & Data Science role. We are building a prototype Copilot that
answers SunGrid member questions from 14 synthetic knowledge-base documents (RAG) and calls a separate
eligibility service (`stub_tools.py`) for rooftop-rebate eligibility questions.

Part of the grade is judgement. Simple, correct, tested and honestly evaluated beats clever.
Do not gold-plate. The repo will be read and reviewed by others, so keep it clean and explainable.

## Hard rules (never violate)
1. Never edit `stub_tools.py`. Call it only through `eligibility/adapter.py`.
2. No secrets in the repo. Keys come from environment variables / a git-ignored `.env`. Never print, log,
   echo, `cat` or commit a key. Never read the contents of `.env`; you may check that a variable is set.
3. The eligibility hard gate is enforced in Python (`eligibility/gate.py`), not in a prompt. If the tool
   returns `eligible=False`, the user-facing text is built from the tool's `reason` only: no amount, no
   estimate, no "you would normally get". The LLM must never see `estimated_rebate_usd` unless eligible=True.
4. No document file names or doc IDs in source code. Doc-specific facts live only in
   `config/doc_manifest.yaml`.
5. The query category is a retrieval filter, not a router. The only early exit is a `non_relevant`
   decline, and it requires BOTH a confident classifier label AND weak unfiltered retrieval.
6. Provider-specific code lives only in `src/sungrid_copilot/llm/`. Everything else uses `LLMClient`.
7. Answers must be grounded in retrieved chunks and cite their sources. If the chunks do not support an
   answer, abstain and say so. Never fill gaps from general knowledge.
8. No agent frameworks (LangChain, LlamaIndex, LangGraph, etc.). No new dependencies without asking.
9. Cross-platform: use `pathlib`, no bash-only scripts, assume the author may be on Windows.

## Architecture: LLM chooses, code enforces
```
query
 1. classify -> {category, confidence, needs_eligibility_check}   (1 LLM call, JSON validated by Pydantic)
 2. retrieve (local and cheap, so always run both searches):
      unfiltered top-k, and filtered top-k (category IN chunk.primary, chunk.secondary) if in scope
      use FILTERED when category is in scope AND confidence >= CLASSIFIER_MIN_CONF
        AND filtered top-1 is within FALLBACK_MARGIN of unfiltered top-1
      otherwise use UNFILTERED and record the reason: low_classifier_confidence |
        non_relevant_uncertain | unfiltered_clearly_better (margin exceeded or filtered empty)
 3. decline (the only early exit) only if category == non_relevant AND confidence >= NON_RELEVANT_MIN_CONF
      AND unfiltered top-1 < NON_RELEVANT_SCORE_CEILING -> polite decline, log, stop
 4. needs_eligibility_check -> eligibility flow (below)
    else -> compose grounded answer with citations, or abstain
 5. append one JSONL record to logs/queries.jsonl
```
Categories are configuration: `config/categories.yaml` is the single source of truth (snake_case `name`,
`display_name`, `description`, `examples`). Today: `program_policies`, `incentive_rebate`, `billing_account`,
`technical_installation`, `company_updates`. `non_relevant` is a built-in reserved query label, never listed
there and never on a document. Adding a category is a YAML edit plus manifest entries, no code change.
Retrieval settings in `config.yaml`: `top_k`, `classifier_min_conf`, `non_relevant_min_conf`, `fallback_margin`,
`non_relevant_score_ceiling` (the last two set from `calibrate` on the dev set, never hard-coded).

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
- Embeddings: local fastembed (ONNX runtime, no PyTorch; default `BAAI/bge-small-en-v1.5`, configurable via
  `embedding.model`), independent of the chat provider. Store the embedding model name in the index; on mismatch fail loudly and say to re-ingest.
- Vector store: Chroma persistent in `.chroma/` (git-ignored). Ingestion is idempotent and rebuilds cleanly.

## Config
- Non-secret settings: `config/config.yaml` (provider, models, top_k, thresholds, timeouts).
- Secrets and provider selection: environment variables, documented in `.env.example` (placeholders only).
- `LLM_PROVIDER` = `azure_openai` | `openai` | `anthropic` | `gemini` | `fake`.
- Azure: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`.
- Only Azure is tested end to end. Say so in the README; do not claim the others are verified.

## Member-facing text and escalation
- All fixed member-facing text lives in `config/messages.yaml` (with `{placeholders}`). Code fills
  placeholders; it never writes member-facing prose. LLM-written text appears only as grounded answers.
- Escalation (`escalated=True`, "flagged for human review"): abstained answers, answers the composer marks
  `needs_human_review` (safety, disputes/appeals, conflicting or incomplete sources), `TIER_NOT_HOUSEHOLD`,
  `TOOL_ERROR`, too many clarification turns, and any non-content-filter LLM failure. A content-filter
  rejection is declined without escalation and makes no further LLM calls. An out-of-scope decline is not
  escalated.
- After an eligibility decision, LLM "what happens next" text is appended only if `guard.check_final_text`
  passes on the complete reply; otherwise the deterministic rendering is sent alone.

## Logging
One JSONL record per handled message in `logs/queries.jsonl` (git-ignored): timestamp, outcome, category,
confidence, filter used, fallback reason, retrieved ids + scores, service called, gate verdict, escalated +
escalation code, guard violations, per-call and total tokens, latency per step, estimated cost. This feeds the
cost-per-1,000 number and the monitoring section of the design record.
- Privacy defaults: never log the question text, ZIP, income or any slot value; log a SHA-256 hash of the
  text and its length. `logging.include_query_text` (default false) adds the text for local debugging only.
- Agent sessions are in memory only and LLM caches are off for `ask` (`agent.use_llm_cache: false`),
  because the caches store the member's text.

## Evaluation
`eval/questions.yaml` (15-20 questions) + `python -m sungrid_copilot.cli eval`. Automated checks: category match, expected
source in top-k, source cited (answered replies only), outcome, tool called or not, review flag where expected,
no `$` in a non-eligible reply. Reply wording and facts are not auto-checked; answer quality is hand-graded from a
generated CSV. Report counts (for example 15/18), not percentages. Failures are included, never hidden.

## Working agreements
- Plan briefly before large changes. Run the tests after each task. Make small, focused commits.
- Tests never touch the network: use the `fake` LLM provider.
- When you cut a corner or notice a limitation, append one line to `NOTES.md` (what + why). This feeds the
  design record and the code-review document.
- If blocked or if the brief is ambiguous, stop and ask. Do not invent requirements.
