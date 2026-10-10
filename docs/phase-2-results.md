# Phase 2 results

Executed October 9, 2026, America/Toronto. The local ask CLI performed real retrieval and Azure AI Foundry chat inference against the Phase 1 corpus of 530 Azure-embedded chunks. These are smoke checks, not the Phase 4 evaluation or accuracy scores.

## Implemented behavior

LangChain Documents, ChatPromptTemplate, and RunnableLambda connect explicit pgvector retrieval to a small chat adapter. The input question is bounded by QUERY_MAX_BYTES and redacted locally. Index identity is checked before paid embedding requests, and the provider-reported embedding model is checked before retrieval. Retrieval only considers manifest-listed public document IDs and validates their source URL, regulator, and title before chat.

The run settings were six retrieved chunks, minimum cosine similarity 0.30, and a 2048-token completion cap except for the deliberate eight-token truncation check. Similarity is a heuristic, not a probability or a calibrated threshold. Ollama query embedding uses the documented search-query prefix while preserving the existing document-vector identity.

AzureOpenAI uses the configured endpoint/key, deployment, and API version 2024-12-01-preview, with separate system and user messages and max_completion_tokens. Requests omit temperature, top_p, penalties, logprobs, and max_tokens; the actual deployment accepted that request shape. SDK retries are disabled. The cap includes reasoning and visible output tokens, as described by the [OpenAI token-cap reference](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create) and [Azure reasoning guide](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning).

Both chat messages pass through local Presidio redaction before transmission. The model returns supported/claims JSON with numbered sources. Invalid structure, missing/invalid citation numbers, model-generated URLs, filtered output, and incomplete responses are withheld. Generated claim text is redacted before output. Source links come from stored provenance, including an HTML anchor where present or a one-based PDF page fragment. Citation validation verifies references and structure; it does not prove that each claim follows from its cited text.

Ollama chat uses /api/chat with stream false, JSON output, and num_predict; its transport contract is mocked. Bedrock uses boto3 Converse with a separate system block, a user message, and maxTokens; its contract is tested with boto3 Stubber against the installed SDK. All AWS endpoints remain local to Floci. Live Ollama and real Bedrock inference were not run.

## Live smoke checks and usage

All rows below use Azure embeddings, text-embedding-3-small at 1536 dimensions, and Azure chat, provider-reported model gpt-5.4-mini-2026-03-17. The deployment name and endpoint fingerprint remain in the ignored run journals. Each normal query makes one embedding request and at most one chat request. No LLM judge or evaluation request was made.

| Check | Run ID | Result | Embedding input tokens | Chat input tokens | Chat output tokens |
| --- | --- | --- | ---: | ---: | ---: |
| PIPEDA safeguards | d397d66d4ef14e69acd38d660529ccd0 | Answered, two source excerpts | 14 | 1448 | 162 |
| OSFI B-10 exit plans | e74646f9dabe49c3ba153940c4fb32f8 | Answered, one source excerpt | 18 | 1423 | 266 |
| FINTRAC large cash record retention | 339c65ce9e6e43efa754487be7f3161e | Answered, one supporting and one extra reference | 16 | 1296 | 46 |
| Invented B-13 quantum banana report requirement | 20c959fd92634f759f7104fda406c68d | Refused, unsupported_by_context | 17 | 1452 | 12 |
| Chocolate cake question | 0b16156f4cfd450e82be0057aa5e05a6 | Refused, weak_evidence; no chat request | 8 | 0 | 0 |
| PIPEDA with eight-token completion cap | 70869e2d668840c1ab77e9601e2cb1f6 | Refused, incomplete_or_filtered_output; finish_reason length | 14 | 1448 | 8 |
| FINTRAC retention with final prompt | 288db130067c4793862d3d1b0cb63bc9 | Answered, supporting excerpt only | 16 | 1312 | 43 |

Total measured Azure usage for these seven queries: seven embedding requests, six chat requests, 103 embedding input tokens, 8379 chat input tokens, and 537 chat output tokens. All six chat responses reported zero reasoning tokens. No monetary estimate is claimed; the deployment's billing rate was not verified.

The supported answers were inspected against their stored cited excerpts. The PIPEDA answer cited Your responsibilities and How to fulfill these responsibilities; the OSFI answer cited section 2.3.5.1; the final FINTRAC answer cited the large cash transaction record retention excerpt. The first FINTRAC answer also referenced a chunk describing record contents without the retention period. The final prompt requires each cited excerpt to support the claim and asks for the fewest necessary references; the follow-up returned the supporting excerpt alone. This observed improvement does not establish a citation correctness rate.

Switching EMBEDDING_BACKEND to ollama and dimension 768 while retaining the Azure table failed with IdentityMismatch and fresh-table/re-ingestion instructions. Run 02403237b456498f98269fcf2eb9af0a made zero embedding and zero chat requests. The user's .env was not modified for this check.

## Journals, refusals, and limitations

Each query writes a UUID JSON journal in ignored data/runs with backend/deployment/provider model, API version, cap, embedding identity, manifest hash, question/prompt hashes, retrieved chunk IDs/scores, status, citations, and reported token usage. Raw questions, full prompts, discarded raw model responses, keys, and provider error bodies are not stored. Provider failures preserve earlier reported usage; missing usage stays unknown rather than being claimed as zero cost. A process termination before final journaling can leave usage unrecorded. Azure billing remains authoritative.

Weak retrieval skips chat. Model-reported lack of support also refuses. Truncation, filtering, and validation failures use a distinct no-answer message and preserve reported usage. There is no automatic retry with a larger cap or different parameters. Repeating ask requests incurs new usage; eval/judge disk caches belong to Phase 4.

The initial Presidio detector still has the limitations recorded in phase-1-results.md. A system instruction and JSON context boundary do not establish complete prompt injection protection. Phase 3 assesses safety. Semantic support still depends on the model and inspection; Phase 4 measures retrieval and answer/citation quality with 30 to 40 questions. Live PDF-page citations and live Ollama remain unverified; page-link formatting is unit-tested. Backend thresholds may need separate calibration.

## Run and test

Follow design-principles.md for setup and Azure/Ollama settings. Configure an ingested table, start the local Docker runtime and Floci, then run:

```bash
docker compose up -d --wait
uv run compliancelens ask "Under PIPEDA, how should an organization protect sensitive personal information?"
uv run compliancelens ask "How do I bake a chocolate cake?"
uv run pytest --db-integration
uv run ruff check .
uv run ruff format --check .
uv run pre-commit run --all-files
```

Final verification: 95 tests passed, including 13 real PostgreSQL tests in disposable schemas. Coverage includes cosine ordering and public-document filtering, immutable identities, missing index instructions, chat caps/roles/redaction, provider failure and unknown usage, filtered/truncated output, invalid citations, PDF links, and safe failed-run journals. Ruff lint/format and the pre-commit secret scan passed before publication.
