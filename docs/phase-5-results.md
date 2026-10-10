# Phase 5 infrastructure evidence

Completed October 9, 2026 in Toronto. All AWS operations ran on the local Floci 2.2.0 instance; there were zero chat or embedding requests and no real AWS deployment.

Terraform 1.16.4 and Terragrunt 1.1.6 applied one reusable platform module to dev and prod-style local environments, with AWS provider 6.68.0 and archive provider 2.8.1. Each environment has 33 managed resources, and both final repeat plans returned exit code zero with no changes. The original 530-chunk CLI corpus still resides on its existing database; new application tables are empty.

## Verified results

Verification journal: `data/runs/7d41aa36e8674ab3ac3384a54de8bae2.json`, completed October 10, 2026 at 00:53:55 UTC. Journals, state, plans, caches, and generated ZIPs are ignored. Resource names and IDs come from Terraform locals and outputs.

| Check | Dev | Prod-style |
| --- | --- | --- |
| Managed resources | 33 | 33 |
| Raw/intermediate S3 versioning | Distinct versions; prior bytes retrieved | Distinct versions; prior bytes retrieved |
| RDS SQL proxy port | 7002 | 7003 |
| pgvector extension | 0.8.7 | 0.8.7 |
| Configured vector dimension | 1536 | 1536 |
| Synthetic retrieval and HNSW plan | Passed | Passed |
| Application vector rows | 0 | 0 |
| Log retention metadata | 7 days | 30 days |
| Reserved concurrency configuration | 1 | 2 |
| Direct query Lambda response | HTTP 501 scaffold | HTTP 501 scaffold |
| REST API to query Lambda | HTTP 501 scaffold | HTTP 501 scaffold |
| Parse/Chunk/Embed workflow references | Correct deployed ARNs | Correct deployed ARNs |
| Scaffold workflow execution | FAILED explicitly | FAILED explicitly |
| Parse-role simulation: own/other raw bucket | allowed / implicitDeny | allowed / implicitDeny |
| Admin attempt to assume Lambda-only role | AccessDenied | AccessDenied |
| Verification-role read: own/other raw bucket | allowed / AccessDenied | allowed / AccessDenied |
| Dummy password in saved plan or state | Absent | Absent |

The synthetic vector probe runs in a temporary schema with a synthetic model identity and removes it afterward. It does not insert fabricated vectors into an Azure index. Application table creation uses the existing store.py implementation and its immutable identity checks. Both new databases have the verified configured-dimension HNSW index.

The database password is an ephemeral Terraform input using the provider's password_wo argument. Saved-plan ZIP members and state were inspected: the dummy password was absent and the write-only state value was null. Infrastructure input extraction uses explicit example values for SQL credentials, so a private DATABASE_PASSWORD process variable cannot enter provisioning. Azure keys are never exported to Terraform or bundled into Lambdas.

## Fidelity and limits

- S3 version preservation, actual PostgreSQL/pgvector queries, HNSW access, Python Lambda execution, REST API integration, workflow failure propagation, and the tested IAM allow/deny requests were exercised live.
- Lambda memory/concurrency settings and log retention are configuration metadata here; load limits and timed log expiry were not tested. RDS instance class, allocated storage, and private-access flags do not establish AWS networking, durability, encryption, or high availability. These databases run in Docker with local TCP proxies.
- IAM enforcement is enabled through FLOCI_SERVICES_IAM_ENFORCEMENT_ENABLED. The dummy test admin credential deliberately bypasses policy evaluation. The API uses local, unauthenticated POST /query. Floci has documented authorization bypasses and protocol differences; the tested denial paths do not establish complete AWS security equivalence.
- Four Lambda functions are explicit placeholders. Query returns 501 and ingestion raises NotImplementedError; workflow failure is the expected scaffold behavior, not successful ingestion. Application dependencies, provider credential access, actual artifact processing, validation, and RAG through the API belong to Phase 6.
- All database and API endpoints are local. Lambda scaffolds target Python 3.12 ARM64 for this Mac runtime. Cross-platform application packaging remains Phase 6 work. State is local per environment, outside Terragrunt caches; it is not a remote production backend. RDS prevent_destroy protects its managed volume from routine teardown.

The [Floci IAM documentation](https://floci.io/floci/services/iam/), [RDS documentation](https://floci.io/floci/services/rds/), [API Gateway documentation](https://floci.io/floci/services/api-gateway/), [Step Functions documentation](https://floci.io/floci/services/step-functions/), and [Terraform write-only arguments](https://developer.hashicorp.com/terraform/language/manage-sensitive-data/write-only) were checked during implementation. Runtime evidence above is separate from documented support.

## Reproduction and checks

Follow the canonical commands in design-principles.md. From each infra/environments/dev and infra/environments/prod directory, run Terragrunt init, validate, plan with phase5.tfplan, apply that saved plan, then plan -detailed-exitcode. From the repository root:

```bash
export PATH="/opt/homebrew/bin:$PATH"
docker compose up -d --wait
uv run python infra/verify.py
uv run pytest --db-integration
terraform fmt -check -recursive infra
terragrunt hcl fmt --check --working-dir infra
uv run pre-commit run --all-files
```

All 142 tests passed, including PostgreSQL integration tests. Ruff, Terraform and Terragrunt formatting, validation of both environments, repeat plans, and the secret scan passed. The Markdown naming restriction was checked before publication.

An initial verification attempted to assume a Lambda service role as the admin and correctly received AccessDenied. The final module adds a verification-only role with account-root trust and reuses the parse policy for runtime read probes. Production-function trust stays Lambda-only. Enabling IAM enforcement recreated the emulator container; the existing corpus and new infrastructure survived. Phase 6 remains not started.
