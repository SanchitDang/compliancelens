# ComplianceLens

A portfolio project being built toward a source-citing RAG assistant for public Canadian financial regulatory documents from OSFI, FINTRAC, and the Privacy Commissioner/PIPEDA.

Phases 0 and 1 provide verified infrastructure and document ingestion. Ten official documents produced 530 redacted chunks with real Azure AI Foundry embeddings; an unchanged repeat made zero provider requests. Question answering is Phase 2. AWS runs locally on Floci, with no real AWS account. Azure is the Mac backend and incurs usage charges; Ollama is the offline option. Bedrock embeddings are mock-tested only.

The project documentation is the source of truth:

- [Setup, commands, structure, and design rules](docs/design-principles.md)
- [Architecture and verified emulator limits](docs/architecture.md)
- [Phase checklists and current status](docs/phases.md)
- [Phase 0 test evidence and reproduction steps](docs/phase-0-results.md)
- [Phase 1 ingestion evidence and reproduction steps](docs/phase-1-results.md)

Start with the setup commands in design-principles.md. Keep keys only in the ignored .env. The code's chat backend default is Bedrock; the local example explicitly selects Azure. Work on dev and merge to main through pull requests.

Run ingestion with `uv run compliancelens ingest`; run the full suite against the local database with `uv run pytest --db-integration`.
