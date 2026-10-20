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
