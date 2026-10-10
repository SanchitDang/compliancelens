# Phase plan

Read design-principles.md before changing this repository. Finish one phase, record evidence and deviations, update architecture.md, then stop until the user says next. Commands for implemented features are canonical in design-principles.md. Future commands below are planned and unavailable until their phase.

## Phase 0: Scaffold and spikes

Status: done.

Goal: establish the Python project and prove the local infrastructure can support the design.

Deliverables: package/configuration/CLI skeleton, pyproject and lockfile, Ruff, pytest, pre-commit secret scan, ignored secrets, Compose, three infrastructure probes, Lambda SQL connectivity proof, and recorded evidence.

- [x] Create and validate the three source-of-truth docs.
- [x] Create Python 3.12 environment, package, config, and config-check CLI.
- [x] Add README, .env.example, .gitignore, Compose, and pre-commit.
- [x] Pass configuration tests and lint/format checks.
- [x] Start Floci; boto3 creates, writes, and reads an S3 object.
- [x] Create Floci RDS with pgvector; test configured-dimension vectors and HNSW.
- [x] Prove Terraform plus Terragrunt creates an S3 bucket, verified independently.
- [x] Invoke a Lambda that executes SQL against the RDS database on Docker networking.
- [x] Prove emulator and database persistence after restart.
- [x] Record commands, versions, digests, results, limitations, and stop.

Run/test: follow the setup, Compose, Terragrunt, probe, persistence, pytest, and Ruff commands in design-principles.md. Detailed evidence goes in phase-0-results.md.

Deviations: Azure is now an explicitly authorized paid inference option; all AWS stays on Floci. Privacy must precede any Azure text transmission. Phase 0 made no inference calls. Docker, Terraform, Terragrunt, and uv were absent at initial inspection and installed locally through Homebrew with Colima as the free Docker runtime. No database fallback was needed. A pure-Python pg8000 bundle was used for the ARM64 Lambda SQL probe to avoid Mac-native dependency binaries. All runtime probes and 26 unit tests passed; Ruff, the secret scan, Terraform formatting/validation, and Terragrunt HCL formatting passed. See phase-0-results.md for exact evidence.

## Phase 1: Ingestion

Status: done.

Goal: a repeatable, source-preserving corpus in pgvector.

Deliverables: 8 to 12 public official OSFI, FINTRAC, and OPC/PIPEDA HTML/PDF documents, manifest, parsing, heading-aware chunks, metadata, batched embedding adapters, immutable table identity, and idempotency.

- [x] Check official source terms and record URLs, retrieval dates, titles, and hashes.
- [x] Parse HTML/PDF and preserve regulator, document, heading, page/anchor, and URL.
- [x] Explain and test chunking within the selected embedding model's limits.
- [x] Implement and test Azure, Ollama, and mock-tested Bedrock embedding adapters.
- [x] Put PII redaction before every Azure embedding request.
- [x] Create configured-dimension table and verified vector index.
- [x] Reject mismatched embedding identities; record identity on every row.
- [x] Skip re-embedding unchanged hashes; record per-run embedding token usage.
- [x] Test re-runs, changes, failures, and mismatched model/dimension.

Run/test: `uv run compliancelens ingest --prepare-only`, `uv run compliancelens ingest`, and `uv run pytest --db-integration`. Ten documents produced 530 stored chunks. Azure reported 103465 input tokens across 34 requests; the repeat reused all 530 chunks with zero requests. All 58 tests, including nine real database tests, passed, as did Ruff and the pre-commit secret scan. See phase-1-results.md for reproduction and limitations.

Deviations: chunking uses a conservative UTF-8 byte budget rather than a provider-specific tokenizer; all Azure inputs were accepted, while live Ollama remains untested. The minimal Presidio boundary was brought forward from Phase 3 to protect Azure ingestion. Full privacy assessment remains in Phase 3. Interrupted provider runs have no durable partial vector cache; that limitation is documented.

## Phase 2: Local RAG core

Status: done.

Goal: grounded answers with traceable citations and evidence-based abstention.

Deliverables: LangChain retrieval/generation pipeline, small backend interface, AzureOpenAI chat, Ollama chat, boto3 Bedrock Converse, output cap, and CLI.

- [x] Implement all three chat adapters and mock-test their request/response contracts.
- [x] Verify GPT-5 parameter omissions and max_completion_tokens.
- [x] Redact PII before Azure requests and preserve separate system/user messages.
- [x] Retrieve only from a matching embedding identity.
- [x] Cite regulator, document, and section with source URL/page/anchor.
- [x] Refuse weak-evidence questions; test unsupported and out-of-scope cases.
- [x] Record per-run chat token usage and incomplete-output behavior.
- [x] Run actual local questions and state which provider was exercised.

Run/test: `uv run compliancelens ask "question"` and `uv run pytest --db-integration`. Seven live Azure queries covered supported answers, an unsupported requirement, an unrelated request, truncation, and a citation prompt refinement; an additional identity mismatch made zero provider requests. All 95 tests, including 13 real PostgreSQL tests, passed. See phase-2-results.md for usage, reproduction, and limits. Bedrock remains mock-tested only.

Deviations: generation uses a small direct SDK adapter within a LangChain pipeline rather than provider-specific LangChain wrappers, preserving the exact Azure request pattern and explicit usage. Structural citation validation is implemented; semantic citation quality is not claimed and remains Phase 4 measurement. Local redaction was extended to chat before Phase 3 as required.

## Phase 3: Safety

Status: done.

Goal: assess and improve redaction and prompt injection defenses without overstating guarantees.

Deliverables: Presidio assessment, redacted logs/input, untrusted context boundaries, input/output checks, PII and injection fixtures, measured missed cases.

- [x] Evaluate Presidio against Canadian PII examples and document recognizer limits.
- [x] Ensure all Azure text paths and logs pass through redaction.
- [x] Keep retrieved content separate from trusted instructions.
- [x] Add input/output checks and known injection attempts.
- [x] Test malicious source text, input attacks, and PII leakage paths.
- [x] Report caught and missed examples without claiming complete protection.

Run/test: `uv run compliancelens safety-check`, `uv run pytest tests/test_safety.py tests/test_privacy.py`, and `uv run pytest --db-integration`. All 116 tests passed. The local assessment removed 17 of 21 expected query PII values and flagged 11 of 14 attacks, with misses and false positives recorded in phase-3-results.md. A CLI attack made zero provider calls; one ordinary public Azure query verified regression behavior and logged usage. No raw PII or poisoned source fixtures were sent to hosted providers.

Deviations: the initial Azure redaction boundary was implemented earlier. Stronger query redaction has its own policy; the immutable document policy stays unchanged to preserve the ingested index and avoid unnecessary re-embedding. The safety assessment is local with mocked provider leakage tests, rather than a paid adversarial LLM benchmark. Broader PII/injection coverage is not claimed.

## Phase 4: Evaluation

Status: done.

Goal: measure retrieval hit rate, citation correctness, and answer accuracy against the ingested corpus.

Deliverables: 30 to 40 document-grounded questions, expected facts/sources, evaluator, disk cache, usage ledger, readable reports, and measured improvement comparisons.

- [x] Write questions from actual ingested documents with expected sources/key facts.
- [x] Define metric denominators, failure handling, and judge limitations.
- [x] Cache redacted eval and judge responses by full prompt/provider/settings identity.
- [x] Record usage, cache hits, provider/model, corpus version, and configuration.
- [x] Run baseline and report only actual scores.
- [x] Try 2 or 3 controlled improvements and compare actual results.

Run/test: `RETRIEVAL_TOP_K=6 uv run compliancelens eval`, `uv run pytest --db-integration`, and the registered Ruff/pre-commit checks. All 138 tests passed. Azure evaluation completed 34 questions for each of three variants. Final judge answer accuracy was 23/30 for baseline and 27/30 for focused context; all variants refused the four unsupported questions. See phase-4-results.md and eval/results/phase-4.md for denominators, provider identity, costs, and limitations.

Deviations: the initial judge grouped citation decisions by claim; an interrupted development run led to explicit numbered pairs. Its usage and one request with unknown usage remain recorded. A final replay verified decoded-field redaction and safe cache reuse. Two controlled retrieval candidates were measured; defaults remain unchanged pending held-out validation. The judge uses the same Azure deployment as generation, so these are subjective development-set scores.

## Phase 5: Infrastructure on Floci

Status: not started.

Goal: reproducible dev and prod-style AWS-shaped infrastructure entirely on Floci.

Deliverables: Terraform modules, two Terragrunt environments, raw/intermediate S3 storage, Step Functions ingestion workflow, parse/chunk/embed/query Lambdas, API Gateway, scoped IAM, and pgvector RDS.

- [ ] Register module files and all names in design-principles.md first.
- [ ] Define names once in Terraform locals and share references/outputs.
- [ ] Scope IAM policies to required resources and operations.
- [ ] Keep all provider endpoints local and state reliable.
- [ ] Validate, plan, and apply both environments on Floci.
- [ ] Record faithful, shallow, missing, or unsupported behavior per resource.

Run/test: Terraform fmt/validate and Terragrunt init/validate/plan/apply in each registered environment, followed by AWS API verification. Exact commands are added when implemented.

Deviations: none.

## Phase 6: Lambda and API

Status: not started.

Goal: working ingestion orchestration and query requests through emulated AWS services.

Deliverables: Lambda packaging, artifact-based Step Functions flow, query API with validation, and real Floci requests.

- [ ] Package Python dependencies for the Lambda runtime and architecture.
- [ ] Wire parse, chunk, and embed stages end to end using S3 artifact references.
- [ ] Configure selected-provider/network access without committing secrets.
- [ ] Implement request validation and structured API error responses.
- [ ] Test successful/failed ingestion executions and valid/invalid API requests.
- [ ] Confirm citations, abstention, redaction, and model identity through the API.

Run/test: local Step Functions executions and HTTP requests against the Terraform-output API endpoint, plus pytest handler tests. Record actual execution evidence.

Deviations: none.

## Phase 7: Monitoring

Status: not started.

Goal: observable behavior with redacted telemetry and useful local alarms.

Deliverables: structured CloudWatch logs, latency/retrieval/refusal/guardrail/error metrics, single-metric alarms, and inspection commands.

- [ ] Redact before structured logs are emitted.
- [ ] Publish and verify custom metric statistics.
- [ ] Create errors/latency alarms and test their actual transitions.
- [ ] Provide simple log/metric/alarm viewing commands.
- [ ] Document Floci limits versus real CloudWatch.

Run/test: representative API and failure requests, CloudWatch get/filter/statistics/describe calls, and pytest telemetry/redaction tests. Verify evaluation rather than merely alarm creation.

Deviations: avoid metric-math alarms because Floci documents no evaluation for them.

## Phase 8: Wrap up

Status: not started.

Goal: reproducible portfolio evidence and honest resume wording.

Deliverables: CI, concise README linking these docs, architecture diagram, Mac Azure and Windows Ollama setup, real eval results, limitations, and resume-gap report.

- [ ] Add GitHub Actions lint, tests, and Terraform validation.
- [ ] Verify documented setup/run/evaluation commands.
- [ ] Record the backend/model behind every reported number.
- [ ] State plainly that AWS runs on Floci and no real AWS was tested.
- [ ] Claim real Azure AI Foundry inference only after it actually runs.
- [ ] State Bedrock is mock-tested only; compare all three resume bullets to evidence.
- [ ] Suggest accurate wording and remaining gap-closing options without editing the resume.
- [ ] Update all project docs and stop.

Run/test: the complete implemented check suite and clean setup checks, with CI results if available. Publish actual measured evaluation evidence and limitations.

Deviations: Azure calls may incur costs at the user's request. A paid real-Bedrock smoke test is only a possible future option, never part of the current authorization.
