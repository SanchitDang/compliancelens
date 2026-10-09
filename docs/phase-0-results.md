# Phase 0 results

Executed October 8, 2026, America/Toronto, on this Mac with ARM64 Python and Docker. All AWS requests targeted Floci. No Azure, Ollama, or real Bedrock inference requests were made.

## Measured infrastructure results

| Probe | Actual result |
| --- | --- |
| Floci startup | Floci 2.2.0 started and was healthy through Compose on port 4566. |
| boto3 S3 | Created the SDK probe bucket, wrote phase-0.txt, and read identical bytes. |
| Terraform + Terragrunt | init and validate passed; plan added one S3 bucket; apply created it; boto3 head_bucket independently verified it. |
| RDS override | Floci launched a real database using pgvector/pgvector:pg16 through FLOCI_SERVICES_RDS_DEFAULT_POSTGRES_IMAGE. No fallback was needed. |
| Vector extension | CREATE EXTENSION vector succeeded; installed version is 0.8.7. |
| Configured dimension | Created vector(1536) from EMBEDDING_DIMENSION, stored two synthetic vectors with hash/backend/model/dimension metadata. |
| HNSW | Created a cosine HNSW index. The nearest-vector query returned id 1, and EXPLAIN used that index with sequential scans disabled. This is a compatibility check, not a performance benchmark. |
| Lambda networking | Invoked a real Docker-backed python3.12 ARM64 Lambda. It used pg8000 to execute SQL through Floci's advertised RDS endpoint on the shared network and returned sql_result 1 and vector_version 0.8.7. |
| Persistence | After docker compose restart floci, both buckets, the object content, two vector rows, and the HNSW query remained valid. The Lambda invocation passed again without rewriting database rows. |
| Terraform re-plan | terragrunt plan -detailed-exitcode returned 0 and reported no changes. |

The vector rows are explicitly labeled synthetic/synthetic-spike. Their metadata does not claim Azure generated them. The actual immutable application-table identity and refusal behavior will be implemented in Phase 1.

## Tool and image versions

- Python 3.12.15; uv 0.12.24; Terraform 1.16.4; Terragrunt 1.1.6.
- HashiCorp AWS provider 6.68.0, locked in infra/spikes/.terraform.lock.hcl.
- Colima 0.10.3 with macOS Virtualization.framework, ARM64, Docker runtime.
- PostgreSQL 16.15 on aarch64 Linux, measured with SELECT version().
- pg8000 1.31.5 and its pure-Python dependencies were packaged in the Lambda ZIP. Psycopg is the host database driver; pg8000 avoids bundling a Mac native binary into Linux Lambda.
- Floci image digest: floci/floci@sha256:e97cd0c1dc2aa14e7697fb5ef5018404c4d6345169dbd276315f0bed2c7b0520.
- pgvector image digest: pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a.

Tags can move. These digests identify this measured run. Platform support and current tags were checked against Docker Hub before the probe.

## Reproduce

The exact setup sequence is in design-principles.md. It installs Python dependencies, starts Floci, installs the small Lambda dependency bundle, applies the spike with Terragrunt, and saves the Terraform outputs.

With that setup complete, from the repository root:

```bash
uv run compliancelens config-check
uv run python infra/spikes/run.py
docker compose restart floci
docker compose up -d --wait
uv run python infra/spikes/run.py --verify-persistence
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The create-and-probe command is re-runnable for the same local settings and dimension. The persistence mode reads existing content and invokes the existing Lambda; it does not recreate missing resources or rewrite the vectors. If the configured dimension changes, the probe refuses the existing table.

Generated evidence is in ignored data/spikes/results.json and persistence-results.json. It contains query-plan evidence and no provider keys. Terraform state is local in infra/spikes/terraform.tfstate, outside Terragrunt's cache. The wrapper selects Terraform explicitly and reads only endpoint/region from config.py. Do not delete state while intending to manage the same bucket.

Pre-commit is installed. Until files are tracked, run it against the explicit file list rather than claiming an empty --all-files scan tested them. Once tracked, the canonical command is `uv run pre-commit run --all-files`.

## Checks and limitations

The final unit run passed 26 tests covering backend choices, Bedrock defaults, dimension/output limits, secret-safe settings representation, env precedence, unique example variables, and local AWS endpoint enforcement. Ruff lint and format checks passed. All three pre-commit hooks passed against the explicit list of project files, including the secret scan. Terraform fmt -check, Terragrunt hcl fmt --check, and Terragrunt validate passed. .env, Terraform state, and generated probe artifacts were confirmed ignored by git. The docs remain the source of truth.

The secret scan initially flagged literal test AWS/database credentials and an intentionally invalid credential-bearing URL. Four line-specific allowlist pragmas identify those fixtures; no source file is broadly excluded.

Phase 0 verifies S3, RDS/pgvector, IAM role creation, and Lambda SQL connectivity. It does not verify Step Functions, API Gateway, CloudWatch, IAM least-privilege enforcement, RAG behavior, redaction, answer accuracy, or citation quality. Floci logs show IAM policy enforcement is disabled by default; later infrastructure work must enable and assess it.

Azure client/API/parameter choices have documentation support but no live deployment test. No provider key was copied or printed. Bedrock adapters and their mocks belong to later phases, so even mock-tested Bedrock inference is not yet a finished claim. Hosted inference remains unavailable until the PII redaction boundary exists. Output caps are validated configuration; batching, usage ledgers, hash-based embedding reuse, and eval caching are later-phase work.

This Mac had no Docker runtime, Terraform, Terragrunt, or uv initially. They were installed through Homebrew; Colima was started and the Compose plugin was linked into ~/.docker/cli-plugins. The local emulator and its containers remain running. Stop Compose and Colima when finished; persistence volumes are retained. No next-phase work has started.
