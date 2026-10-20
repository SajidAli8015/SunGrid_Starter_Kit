# Notes: shortcuts and limitations

One line per item: what, and why.

- Only Azure OpenAI is tested end to end; the OpenAI, Anthropic and Gemini clients are written against their SDKs and covered only by offline construction tests.
- `complete_json` uses prompt instructions plus Pydantic validation, not provider structured-output features, because those differ across providers and Azure API versions.
- `complete(temperature=None)` falls back to `llm.temperature` from config, so the YAML value is actually used (small deviation from the brief's `temperature=0.0` default).
- `complete_json` returns a `JSONResponse` (value plus raw responses), not the bare model, so token counts and latency are available for the per-query log.
- Only `LLM_PROVIDER` overrides YAML from the environment for now; other settings are YAML-only until there is a need.
- Any exception from a provider SDK is wrapped in `LLMError` (broad catch, secrets redacted, cause chained) so callers handle one error type.
- The fake provider built by the factory returns `{"status": "ok"}` by default so `check-llm` can run offline; tests script their own responses.
- The Anthropic client does not send `temperature`: the installed `anthropic` 1.x SDK no longer accepts it on `messages.create`, so determinism there is not controlled.
- Doc categories for docs 07-14 are our assumption (the kit labels only 01-05, and 06 as ambiguous); only doc 06 has a secondary category, pending evaluation results.
- Manifest `owner` values other than the Incentive Program committee and the Billing team (the only teams the KB names) are plausible placeholders.
- Chunk size uses an approximate token count (words plus punctuation), not the embedding model's tokenizer; good enough for a ~350-token limit, and no current section comes close.
- Oversize sections are split on paragraph, then bullet, boundaries; a single oversize table or paragraph is kept whole rather than cut mid-row/mid-sentence.
- `secondary` is stored in Chroma as a comma-joined string plus one `cat_<category>` boolean per category, because Chroma metadata cannot filter on lists.
- Ingestion always drops and rebuilds the whole collection (14 small docs); no incremental updates, even though `content_hash` would allow them.
- fastembed caches the downloaded model in its default temp-dir cache; a cleaned temp dir means a re-download on the next run.
- `search` uses fastembed's `query_embed`/`passage_embed` as-is; no BGE query instruction prefix or score threshold tuning yet.
- The classifier's confidence is self-reported by the LLM and uncalibrated. It only ever widens search (low confidence -> unfiltered), except in the guarded `non_relevant` exit, which also needs weak unfiltered retrieval.
- The classifier prompt names the Rooftop Rebate Program (for `needs_eligibility_check`) and the fault-code rule refers to "the category whose description covers fault codes" rather than naming a category, so all category text still comes from `config/categories.yaml`.
- The fake LLM's dict keys match the system prompt as well as the last message; tests key on full query strings to avoid accidental matches.
- The margin fallback compares top-1 scores only: when a wrong category's own chunk is the unfiltered top-1 (margin 0), the filter is kept and the right doc can drop out (dev set: 3/80 wrong-label cases at margin 0.05).
- Unfiltered top-1 scores for in-scope and out-of-scope dev queries overlap: general-solar, other-utility and prompt-injection queries score like terse in-scope ones ("E07" 0.635). The score ceiling alone cannot decline safely; the classifier label carries most of that decision.
- The dev set (28 queries) is small and written by us, so thresholds tuned on it are rough; the held-out evaluation set is the honest check.
- The calibration "best ceiling" breaks ties toward the lowest value, because wrongly declining an in-scope question is worse than answering an out-of-scope one (grounding can still abstain).
- Azure's content filter rejects the prompt-injection dev query (d23) with HTTP 400 before the model sees it; the classifier raises `LLMError`. Calibration records it as an error (counted as a miss), and the answer pipeline must treat a classifier failure safely (no answer from guesswork). Errors are not cached, so that call is retried on every calibration run.
- `fallback_margin` set to 0.04 from calibration: wrong-label robustness 78/80 (vs 77/80 at 0.05), and the fallback never fires when the label is right (0/20) at any margin from 0.02 to 0.10; 0.04 is the largest margin with the best count.
- `non_relevant_score_ceiling` kept at 0.60, not the suggested 0.63: "E07" scores 0.635, so 0.63 leaves 0.005 of headroom, and wrongly refusing an in-scope question is the worst outcome. A missed decline (general-solar and other-utility queries at 0.627) is harmless because the answer step abstains when the chunks do not support an answer.
- Multi-doc questions can lose one source to the filter: the lapsed-certification dev query is labelled program_policies (0.90), margin 0.015 keeps the filter, so the rebate doc (unfiltered rank 2) drops out of the top 5. The deciding fact is in the installer certification doc (rank 1), so the answer can still be grounded. Tags left unchanged on purpose.
- `LLMContentFilterError` is mapped for Azure only (HTTP 400 with code `content_filter`, matched by attributes). OpenAI, Anthropic and Gemini signal blocked input differently (or not as an exception) and are not mapped; their rejections stay generic `LLMError`.
