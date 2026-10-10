# Phase 6 application evidence

Completed October 9, 2026 in Toronto. AWS services ran on Floci 2.2.0; embeddings and chat ran on Azure AI Foundry. Bedrock and Ollama inference remain mock-tested only.

## Deployed behavior

Both local environments now run four Python 3.12 ARM64 container-image functions. The shared image contains locked Linux dependencies, the local Presidio/spaCy model, application source, and the public manifest. Each function selects its handler through an image command override. Terraform still manages 33 resources per environment; both environments validated and repeat plans returned exit code zero with no changes.

The uploader verifies a manifest-listed public document hash, uploads it to the raw bucket, and explicitly starts Step Functions. Parse reads the verified bytes; Chunk creates heading-preserving redacted chunks; Embed reuses matching hashes and writes vectors transactionally. Stage events carry document/run identifiers that resolve to deterministic S3 artifacts, never document text or arbitrary bucket/key inputs. A single-document execution preserves other indexed documents. Provider identity and configured dimension remain enforced by store.py.

POST /query validates JSON, fields, question type/size, and content type before provider calls. It reuses the existing RAG pipeline for privacy, retrieval, injection detection, citations, output checks, abstention, and token caps. Responses serialize citation timestamps safely. Invalid requests return 400 or 415; identity mismatch returns 409 with separate-table/re-ingestion instructions; runtime failures return a safe 502 code. Direct-handler tests also cover 405 and invalid base64. Query and ingestion usage journals live in the local intermediate S3 bucket.

## Live results

Representative document: pipeda-accountability, an approved public OPC source. Five real Azure-embedded chunks reside in each environment's separate database, with a 1536-dimension HNSW index. The existing ten-document, 530-chunk CLI corpus remains intact on its original database.

| Check | Dev | Prod-style local |
| --- | --- | --- |
| Parse → Chunk → Embed | SUCCEEDED | SUCCEEDED |
| Stored representative chunks | 5 | 5 |
| Initial embedding requests / input tokens | 1 / 763 | 1 / 763 |
| Unchanged repeat | 5 chunks reused; zero requests | 5 chunks reused; zero requests |
| Unregistered-document workflow | FAILED | FAILED |
| Malformed JSON / extra fields / blank / oversized question | HTTP 400 | HTTP 400 |
| Injection request | Refused before provider calls | Refused before provider calls |
| Explicitly supported question | Answered with trusted citations | Answered with trusted citations |
| Unsupported question | Refused for weak evidence | Refused for weak evidence |
| Synthetic email in question | Cited answer; email absent from response/journal | Cited answer; email absent from response/journal |

Final verification journals are data/runs/7f4760464e9a4342be63a9f996eed91b.json for dev and data/runs/645be43aead24e338cb59c4ca7ca52a9.json for prod-style. An additional dev probe returned HTTP 415 for non-JSON content and HTTP 409 after temporarily changing the query function's configured dimension to 768; the original configuration was restored. Its S3 query journal reports zero embedding/chat requests. Probe journal: data/runs/4eea1e4a41d0404d9428f4434e4808b8.json.

These are functional examples, not a new accuracy benchmark. The Phase 4 development evaluation remains the published metric comparison.

## Azure usage, including development failures

Usage summary: data/runs/fe660d09e64340649270f6bc736387cb.json, aggregating all Phase 6 ingestion/query S3 journals. Actual reported models were text-embedding-3-small and gpt-5.4-mini-2026-03-17. Every paid embedding/chat request below used Azure AI Foundry.

| Usage | Dev | Prod-style | Total |
| --- | --- | --- | --- |
| Document embedding requests | 1 | 1 | 2 |
| Document embedding input tokens | 763 | 763 | 1526 |
| Query embedding requests | 5 | 3 | 8 |
| Query embedding input tokens | 90 | 49 | 139 |
| Chat requests | 4 | 2 | 6 |
| Chat input tokens | 4428 | 2213 | 6641 |
| Chat output tokens | 337 | 240 | 577 |
| Requests without reported usage | 0 | 0 | 0 |

Total embedding input was 1665 tokens. The ledger includes an initial broadly worded supported-case question that was refused and a successful generated answer whose HTTP serialization failed before the timestamp fix. Their provider usage was preserved in S3. SDK retries and workflow retries for paid embedding are disabled. Completion tokens stay capped by LLM_MAX_OUTPUT_TOKENS; no evaluation or judge requests ran in this phase. No dollar estimate is supplied without verified deployment pricing.

## Packaging, credentials, and checks

The attempted ZIP dependency layer contained 392597103 unpacked bytes and its direct upload failed. AWS documents a 250 MB combined unpacked ZIP/layer limit, so the final implementation uses a container image. See [AWS Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) and [Floci locally built image support](https://floci.io/floci/services/lambda/#locally-built-images), checked during implementation. No ECR push or real AWS deployment occurred.

The code/requirements/Dockerfile fingerprint is 3064c15bf33d2404179fdb8e0bc527911e1b51674c60ed6e2b295f49b62fcc6d. Rebuilding application code with unchanged locked dependencies reused the same Docker image. The Linux import/model checks passed; all 162 tests, including PostgreSQL integration tests, passed. Ruff, Terraform/Terragrunt formatting, both validations, repeat plans, and the secret scan passed.

Azure keys remain only in the ignored host .env, mounted read-only at /run/compliancelens/.env through Floci's Docker flags. Application archives and the image contain no .env; the application archive and both Terraform states were checked for the actual Azure key. Both states also omit the SQL password. Lambda configuration contains only nonsecret runtime/bucket/database routing values. Runtime mounts were inspected and were read-only.

This local mount grants trusted application containers access to the host settings file. It is not a cloud secrets-management deployment. API authentication, TLS, production networking, real AWS limits, Windows/x86_64 packaging, and live Ollama/Bedrock inference were not established. The runtime image uses the Python 3.12 base tag; the dependency lock and code fingerprint do not make that upstream tag immutable. Chunk/embedding stages trust IAM-protected intermediate artifacts produced by the preceding stage. Monitoring metrics and alarms remain Phase 7.

## Reproduction and deviations

Follow design-principles.md for setup. Build with uv run python infra/package.py, start Compose with the registered read-only mount flag, then plan/apply both environments using phase6.tfplan. Run:

```bash
uv run python infra/application.py --environment dev --document-id pipeda-accountability --verify-api
uv run python infra/application.py --environment prod --document-id pipeda-accountability --verify-api
uv run pytest --db-integration
terraform fmt -check -recursive infra
terragrunt hcl fmt --check --working-dir infra
uv run pre-commit run --all-files
```

The verification command intentionally exercises the accountability document's specific supported statement. It does not create a universal question for every manifest document. To ingest another registered source, omit --verify-api and change --document-id. Refresh public downloads and rebuild the manifest-containing image before ingesting a changed source.

Container images replace the planned ZIP packaging because of dependency size. Fixed-name Lambda replacements use destroy-before-create; API deployment's prior lifecycle propagated an impossible create-before-destroy order to these functions. Replacement can cause local downtime, and real AWS deployment lifecycle was not verified. The timestamp serialization fix has a regression test. Live ingestion uses one representative document per environment to limit Azure costs; the full CLI corpus is preserved rather than re-embedded. Phase 7 remains not started.
