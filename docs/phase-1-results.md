# Phase 1 results

Executed October 8, 2026, America/Toronto, using Azure embeddings and the existing local Floci RDS instance. This phase implements ingestion. Chat answers, citation quality scores, and answer accuracy evaluations belong to later phases.

## Corpus and source records

Ten official public documents were downloaded. data/manifest.json records each full title, regulator, original and resolved URL, UTC retrieval timestamp, and SHA-256 checksum. Local HTML/PDF copies are in ignored data/raw. Three OSFI documents cover B-10, B-13, and E-21; three FINTRAC documents cover compliance programs, identification timing, and financial-entity records; OPC documents cover PIPEDA accountability, consent, safeguards, and the PDF Privacy Guide for Businesses.

| Document ID | Format | Sections or pages | Stored chunks |
| --- | --- | ---: | ---: |
| osfi-b10 | HTML | 62 | 74 |
| osfi-b13 | HTML | 82 | 82 |
| osfi-e21 | HTML | 36 | 39 |
| fintrac-compliance | HTML | 15 | 70 |
| fintrac-identification | HTML | 37 | 82 |
| fintrac-records | HTML | 52 | 103 |
| pipeda-accountability | HTML | 4 | 5 |
| pipeda-consent | HTML | 6 | 7 |
| pipeda-safeguards | HTML | 4 | 4 |
| pipeda-business-guide | PDF | 43 pages | 64 |

The measured database totals are 195 OSFI, 255 FINTRAC, and 80 OPC chunks. FINTRAC pages include lengthy glossaries, so this is a representative corpus, not an optimized one.

The publishers' [OSFI terms](https://www.osfi-bsif.gc.ca/en/terms-conditions), [Canada.ca terms linked by FINTRAC](https://www.canada.ca/en/transparency/terms.html), and [OPC terms](https://www.priv.gc.ca/en/privacy-and-transparency-at-the-opc/terms-and-conditions-of-use/) permit non-commercial reproduction subject to attribution and accuracy conditions. The manifest preserves attribution and original URLs. Raw files and logos are not published. robots.txt was checked during download, official-host redirects are validated before following, requests are spaced, and downloads have a size limit.

## Chunking and privacy

Beautiful Soup extracts the HTML main content and headings, stripping navigation, forms, scripts, and footer content. Chunks do not cross section boundaries. LangChain's RecursiveCharacterTextSplitter uses a 1500-byte limit and 200-byte overlap, preferring paragraph, line, sentence, and word boundaries. Redacted embedding input is bounded to 1900 UTF-8 bytes, leaving room for title and heading. All actual Azure batches were accepted. This is a conservative budget for the English corpus, not a measured token count or a live validation of Ollama limits. Provider token usage is measured separately.

HTML metadata includes regulator, title, section heading, original section anchor where present, source URL, and retrieval time. PDFs preserve one-based page numbers; their section labels are Page N rather than inferred headings. Image-only PDFs fail instead of silently ingesting empty text. OCR and PDF layout reconstruction are not implemented.

Presidio and the local pinned spaCy en_core_web_sm 3.8.0 model redact names, email addresses, phones, card numbers, IP addresses, and nine-digit Canadian identifier patterns before Azure requests. The redacted text is stored in pgvector. Explicit section references that resemble IPv4 addresses are preserved. The actual run recorded 87 PERSON, 2 EMAIL_ADDRESS, 6 PHONE_NUMBER, and 1 IP_ADDRESS replacements across preparation steps. Those counts are detector output, not confirmed PII or precision/recall scores; repeated processing and false positives can affect them. Birth dates, addresses, bank accounts, obfuscated PII, and uncommon names are not comprehensively covered. Phase 3 will assess those limits further.

## Actual Azure embedding runs

Backend: azure. Deployment and provider-reported model: text-embedding-3-small. Embedding API version: 2024-04-01-preview. Dimension: 1536. Batch size: 16. Table: regulatory_chunks_azure. The HNSW index uses vector_cosine_ops. Identity includes backend/model/dimension, endpoint/API fingerprint, and redaction/prompt policy, with separate checks for provider model drift.

| Run | Stored rows | New embedding inputs | Reused chunks | Provider requests | Reported input tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| a990745abdee4c4cbf443b2a3925d235, first ingestion | 530 | 530 | 0 | 34 | 103465 |
| 9acea29f255e4cfc83018377bb5f9143, unchanged repeat | 530 | 0 | 530 | 0 | 0 |

Per-run JSON reports live in ignored data/runs. Only aggregated, non-secret results are recorded here. No dollar estimate is claimed because the configured Azure deployment's billing rate was not verified. No chat, judge, or real Bedrock request was made. Real Azure embedding inference is proven; real Azure chat inference is not yet proven.

Changing EMBEDDING_BACKEND to ollama with dimension 768 while keeping the Azure table refused with IdentityMismatch and instructions to use a separate table or a fresh table. That attempt made zero embedding requests. Unit tests mock Azure and Ollama transport; the Bedrock Titan v2 adapter is verified with boto3 Stubber. Live Ollama and real Bedrock embeddings remain untested.

## Idempotency and failure behavior

Content hashes cover the redacted embedding input, including document title and heading. Matching hashes within the same identity reuse stored vectors. Identical embedding inputs are deduplicated within a run. Changed chunks get new vectors; stale chunks are removed when their document is successfully replaced. Documents removed from the manifest are pruned after a successful run. Each document replacement is transactional; a failed write preserves its previous rows.

Provider output must have the configured dimension, finite nonzero vectors, and the expected batch indexes/count. A mismatch fails before writing vectors. Successful reported usage is retained even when validation fails. Requests without reported usage are marked explicitly; an API timeout is not claimed to cost zero. SDK retries are disabled and INGEST_MAX_EMBEDDING_BATCHES caps new batches before any call.

There is no durable vector cache for a partially failed provider run before its document writes. Such a retry can incur additional embedding usage. Run journals record completed responses; a hard process termination between receiving a response and journaling it can leave usage unknown. Consult Azure billing for authoritative charges.

## Run and test

First run uv sync, start Compose, and configure the local database and selected embedding settings as described in design-principles.md. With the existing Phase 0 RDS endpoint configured:

```bash
uv run compliancelens ingest --download-only
uv run compliancelens ingest --prepare-only
uv run compliancelens ingest
uv run compliancelens ingest
uv run pytest --db-integration
uv run ruff check .
uv run ruff format --check .
uv run pre-commit run --all-files
```

The second ingestion should reuse unchanged hashes and report zero provider requests. Use --refresh when intentionally retrieving newer official documents. Switching providers requires a separate configured table. PostgreSQL tests use disposable schemas and do not write into the corpus table.

Final checks: 58 tests passed, including nine real PostgreSQL tests for hash reuse, changed content, stale document removal, dimension/model/backend/policy mismatch, provider drift, and transactional rollback. Ordinary pytest skips the database tests unless --db-integration is supplied. Ruff lint/format and the pre-commit secret scan passed.
