# ComplianceLens

A portfolio project being built toward a source-citing RAG assistant for public Canadian financial regulatory documents from OSFI, FINTRAC, and the Privacy Commissioner/PIPEDA.

Phases 0 through 6 provide verified infrastructure, document ingestion, and cited question answering. Ten official documents produced 530 redacted chunks with real Azure AI Foundry embeddings; an unchanged repeat made zero provider requests. The ask CLI retrieves public evidence, answers supported questions, and refuses weak or unsupported requests. Azure chat was exercised live. Local safety checks cover known attacks and detected PII; the results document remaining misses and false positives. AWS runs locally on Floci, with no real AWS account. Azure is the Mac backend and incurs usage charges; Ollama is the offline option. Bedrock embeddings and chat are mock-tested only.

The project documentation is the source of truth:

- [Setup, commands, structure, and design rules](docs/design-principles.md)
- [Architecture and verified emulator limits](docs/architecture.md)
- [Phase checklists and current status](docs/phases.md)
- [Phase 0 test evidence and reproduction steps](docs/phase-0-results.md)
- [Phase 1 ingestion evidence and reproduction steps](docs/phase-1-results.md)
- [Phase 2 RAG evidence and reproduction steps](docs/phase-2-results.md)
- [Phase 3 safety measurements and known limits](docs/phase-3-results.md)
- [Phase 4 evaluation evidence](docs/phase-4-results.md)
- [Phase 5 infrastructure evidence and emulator limits](docs/phase-5-results.md)
- [Phase 6 Lambda workflows, query API, and Azure usage](docs/phase-6-results.md)
- [Measured Azure evaluation comparison](eval/results/phase-4.md)

Start with the setup commands in design-principles.md. Keep keys only in the ignored .env. The code's chat backend default is Bedrock; the local example explicitly selects Azure. Work on dev and merge to main through pull requests.

Run ingestion with `uv run compliancelens ingest`, ask with `uv run compliancelens ask "Under PIPEDA, how should sensitive personal information be protected?"`, and test against the local database with `uv run pytest --db-integration`.

Run the local synthetic safety assessment with `uv run compliancelens safety-check`; it makes no provider requests.

Run the 34-question development evaluation with `RETRIEVAL_TOP_K=6 uv run compliancelens eval`. It compares three retrieval settings, caches safe responses locally, and records Azure token usage and judge limitations.

Terraform deploys separate dev and prod-style stacks on Floci with working image-based Lambda ingestion and a cited-answer query API. Follow the build/apply commands in design-principles.md, then verify with `uv run python infra/application.py --environment dev --document-id pipeda-accountability --verify-api`. Each application database contains five representative Azure-embedded chunks; the full CLI corpus remains separate. Keys are read from a local read-only .env mount.
