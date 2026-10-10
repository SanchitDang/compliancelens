# Phase 4 evaluation evidence

Completed October 9, 2026 in Toronto. [Measured comparison and metric definitions](../eval/results/phase-4.md) and [machine-readable provenance and usage](../eval/results/phase-4.json) own the scores. All measured inference used Azure AI Foundry, gpt-5.4-mini-2026-03-17 for answers and judges, and Azure text-embedding-3-small at 1536 dimensions for retrieval. No live Bedrock or Ollama inference was performed.

## Delivered behavior

The eval command validates 34 public-document questions against exact chunk IDs, hashes, excerpts, and manifest provenance before provider calls. It evaluates the current retrieval configuration plus wider and focused contexts. Public gold facts reach only the judge, never retrieval or answer generation. Every evaluated question remains in its metric denominator, including refusals and failures. Full journals persist after each question and on interruption, with safe exception types, actual provider models, token usage, unknown usage, cache hits, configuration, and corpus/benchmark identity.

Chat caches include redacted prompts, backend, deployment, API version, endpoint fingerprint, output cap, corpus/benchmark versions, and safety policy. Both the full response and decoded JSON fields must pass local redaction checks before storage or reuse. Judge fields are redacted before serialization and again at the provider boundary. Cached responses retain original usage separately from zero new cache-hit usage. Query vectors are cached by redacted question and immutable embedding/provider identity, with dimension checks. Deployment aliases require explicit cache refresh after upgrades; incomplete or detected-sensitive responses are never cached.

The focused candidate increased judge-scored answer accuracy from 23/30 to 27/30 in the final Azure verification. See the comparison for citation denominators, exact retrieval hits, expected refusals, and all usage. Defaults remain unchanged; use `RETRIEVAL_TOP_K=3 uv run compliancelens ask "question"` to try the measured focused query setting. Reproduce the comparison with `RETRIEVAL_TOP_K=6 uv run compliancelens eval`.

## Checks and deviations

All 138 tests passed, including real PostgreSQL tests. The evaluator tests cover prompt/provider/settings cache isolation, encoded JSON PII, incomplete and corrupt caches, numbered judge decisions, failure denominators, unknown usage, vector model/dimension checks, stale gold references, and safe identity-failure journals before inference. Ruff lint/format and the pre-commit secret scan passed. The Markdown naming restriction was checked before publication.

An interrupted judge-development run revealed decisions grouped by claim instead of source; numbered pair IDs fixed the contract. Its costs and one answer request with unknown usage remain in the ledger. The completed comparison was replayed after strengthening decoded-field privacy checks; only safe, identical responses were reused. The published scores come from that final verification.

The benchmark is a development set, not held out. Same-model judgments can disagree with a reasonable source-grounded reading; the comparison documents a concrete example. The gold completeness rubric and selected exact chunks are not exhaustive legal ground truth. Narrower context is a promising measured candidate, rather than evidence of general production accuracy. No dollar cost is estimated without deployment pricing. Phase 5 remains not started.
