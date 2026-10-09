# ComplianceLens

A portfolio project being built toward a source-citing RAG assistant for public Canadian financial regulatory documents from OSFI, FINTRAC, and the Privacy Commissioner/PIPEDA.

Phase 0 provides the Python scaffold and verified infrastructure probes. Document ingestion and question answering are not implemented yet. AWS runs locally on Floci, with no real AWS account. Azure AI Foundry is the planned Mac inference backend and may incur usage charges; Ollama is the offline option. Real Azure inference has not run, and real Bedrock has not been tested.

The project documentation is the source of truth:

- [Setup, commands, structure, and design rules](docs/design-principles.md)
- [Architecture and verified emulator limits](docs/architecture.md)
- [Phase checklists and current status](docs/phases.md)
- [Phase 0 test evidence and reproduction steps](docs/phase-0-results.md)

Start with the setup commands in design-principles.md. Keep keys only in the ignored .env. The code's chat backend default is Bedrock; the local example explicitly selects Azure. Phase 0 makes no inference requests.
