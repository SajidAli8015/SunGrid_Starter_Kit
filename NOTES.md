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
