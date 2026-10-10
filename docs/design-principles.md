# Design principles

This file owns repository conventions. Read it and phases.md at the start of every session. Before creating a file, module, environment variable, or resource, check this registry. Add new entries here before implementing them. If code disagrees with this document, report the disagreement and resolve it explicitly.

## Folder and file registry

```text
README.md                       brief setup and documentation links
pyproject.toml                  Python dependencies, tools, CLI entry point
uv.lock                         resolved Python dependency versions
.python-version                 Python 3.12 selection
.env.example                    sole registry of application environment variables
.env                            ignored local secrets and machine settings
.gitignore                      ignored secrets, state, downloads, generated outputs
.pre-commit-config.yaml         Ruff and secret scan hooks
docker-compose.yml              Floci, storage volumes, shared Docker network
src/compliancelens/
  __init__.py                   package marker
  config.py                     all application settings and validation
  cli.py                        supported CLI commands
  documents.py                  manifest validation, download, parsing, and chunks
  embeddings.py                 Azure, Ollama, and Bedrock embedding adapters
  privacy.py                    local Presidio redaction before provider calls
  store.py                      pgvector identity, hash reuse, and document replacement
  ingestion.py                  ingestion orchestration and usage reports
  chat.py                       chat adapters and safe provider usage
  rag.py                        LangChain query pipeline, evidence checks, citations
tests/
  test_config.py                configuration validation tests
  test_spikes.py                local endpoint safety and spike checks
  conftest.py                   optional database integration flag
  test_documents.py             parsing, provenance, chunking, and manifest checks
  test_embeddings.py            mocked batching, dimensions, usage, and redaction
  test_privacy.py                initial local redaction examples
  test_store.py                  PostgreSQL tests using isolated temporary schemas
  test_ingestion.py              orchestration and failed-run reporting
  test_chat.py                   chat contracts, caps, redaction, and incomplete output
  test_rag.py                    retrieval, abstention, citations, and query journals
infra/
  spikes/
    main.tf                     Phase 0 AWS provider and bucket
    terragrunt.hcl              Phase 0 Terraform wrapper
    run.py                      S3, RDS/vector, and Lambda network probes
    lambda_handler.py           SQL connectivity probe, packaged by run.py
    .terraform.lock.hcl         committed provider version and checksum lock
    backend.tf                  generated only in Terragrunt cache, stable local state path
  modules/                      Phase 5 reusable Terraform infrastructure
  environments/dev/             Phase 5 local development configuration
  environments/prod/            Phase 5 production-style local configuration
data/
  manifest.json                 Phase 1 public source inventory
  raw/                          ignored downloaded documents
  floci/                        ignored emulator data
  spikes/                       ignored Lambda packages and probe state
  runs/                         ignored ingestion and query usage journals
eval/
  questions.json                Phase 4 document-grounded questions
  results/                      Phase 4 publishable measured reports
  cache/                        ignored cached redacted eval and judge responses
docs/
  architecture.md               current and planned system, verified limits
  phases.md                     phase checklists, commands, status, deviations
  design-principles.md           this registry and conventions
  phase-0-results.md             commands, measured spike results, prerequisites
  phase-1-results.md             measured corpus, ingestion, usage, and re-run evidence
  phase-2-results.md             measured RAG answers, refusals, usage, and limits
```

Phases 0 and 1 are complete; Phase 2 files above are registered. Future files must be registered here first. No empty marker files or duplicate setup guides. Generated virtual environments, lockfiles, caches, and Terraform state belong at their tool-standard paths and are covered by .gitignore.

## Naming and ownership

- Work on the dev branch. Push changes to dev, open a pull request into main, and merge through that pull request. Do not commit feature work directly to main. The initial Phase 0 publication bootstraps main before dev is created.

- Python files, modules, functions, variables, tables, and columns use snake_case. Classes use PascalCase. Constants and environment variables use UPPER_SNAKE_CASE.
- Configuration lives only in config.py. Use typed settings. Never print settings or secret values. Env-file loading must not override explicit process variables.
- Each environment variable is assigned once in .env.example. Docs reference its name rather than maintaining a second full settings file. Windows instructions describe the necessary overrides.
- Terraform resources use descriptive snake_case labels. AWS names use compliancelens-{environment}-{purpose}. A Terraform locals block owns each name once; consumers use references or Terraform outputs.
- Phase 0 resource names are owned by infra/spikes/main.tf locals: raw_bucket = compliancelens-dev-spike-raw, sdk_bucket = compliancelens-dev-spike-sdk, database = compliancelens-dev-spike-db, lambda_function = compliancelens-dev-spike-query, lambda_role = compliancelens-dev-spike-lambda. run.py reads these values from terraform output JSON and must not invent replacements.
- The Compose service is floci. The shared network is compliancelens-local; storage volume is floci-data. These are owned by docker-compose.yml.
- The Phase 0 table is compliancelens_spike_chunks; its index is compliancelens_spike_chunks_embedding_hnsw. Both are owned by infra/spikes/run.py. Columns: id, content_hash, embedding_backend, embedding_model, embedding_dimension, embedding. It contains synthetic vectors, not real document embeddings.
- Phase 1 uses VECTOR_TABLE, initially regulatory_chunks_azure. Its companion identity table is {VECTOR_TABLE}_identity; the index is {VECTOR_TABLE}_embedding_hnsw. store.py owns those derived names. Identity columns: backend, model, dimension, fingerprint, provider_model. Chunk columns: id, document_id, content_hash, text, regulator, document_title, section_heading, page, anchor, source_url, retrieved_at, embedding_backend, embedding_model, embedding_dimension, embedding. Backend, model, and dimension are immutable per table. Fingerprints also include endpoint, API version, embedding prompt policy, and redaction policy. Querying a mismatched index refuses with separate-table/fresh-table instructions. Provider-reported model identity is checked for drift.
- New Phase 1 settings are registered once in .env.example: DATABASE_HOST, DATABASE_PORT, VECTOR_TABLE, CHUNK_SIZE_BYTES, CHUNK_OVERLAP_BYTES, PII_SPACY_MODEL, and INGEST_MAX_EMBEDDING_BATCHES. Database host/port refer to the existing Floci RDS endpoint. No new database resource is needed. Tables use regulatory_chunks_{backend}, with a model-specific suffix when using multiple models of one backend.
- Source choices and URLs live only in data/manifest.json. Document IDs use regulator-purpose slugs. Downloads stay in ignored data/raw, usage reports in ignored data/runs with UUID run names. Publish aggregated evidence in docs/phase-1-results.md.
- Phase 2 settings are RETRIEVAL_TOP_K (initial 6), RETRIEVAL_MIN_SIMILARITY (initial 0.30), and QUERY_MAX_BYTES (initial 2000), registered once in .env.example. These bound context, gate weak retrieval, and bound question size; similarity is a heuristic, not a confidence probability. Chat uses the existing LLM_MAX_OUTPUT_TOKENS cap.
- Phase 2 uses LangChain Documents, ChatPromptTemplate, and RunnableLambda to connect retrieval and generation. Queries only use manifest-listed public sources from a matching index. Ollama query embeddings use the search-query prefix while retaining the existing document-vector identity. Chat returns supported/claims JSON with numbered source references; rag.py validates references and builds citation metadata and URLs from stored provenance, never model-generated URLs. Unsupported, invalid, filtered, or truncated output is withheld. Logs record redacted outputs and prompt/question hashes, never raw questions or provider error bodies.
- Shared logic has one implementation. Tests may use fixtures but must not copy production logic.

## Commands

Run from the repository root unless a command explicitly changes directory.

```bash
export PATH="/opt/homebrew/bin:$PATH"
brew install uv colima docker docker-compose terragrunt
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
mkdir -p ~/.docker/cli-plugins
ln -s /opt/homebrew/lib/docker/cli-plugins/docker-compose ~/.docker/cli-plugins/docker-compose
colima start --cpu 4 --memory 6 --disk 30 --vm-type vz --mount-type virtiofs
uv python install 3.12
uv sync --group dev
cp .env.example .env
chmod 600 .env
uv run compliancelens config-check
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pre-commit install
uv run pre-commit run --all-files
docker compose config --quiet
docker compose up -d --wait
mkdir -p data/spikes
uv pip install --python .venv/bin/python --target data/spikes/lambda pg8000==1.31.5
cd infra/spikes
terragrunt init
terragrunt validate
terragrunt plan -out=phase0.tfplan
terragrunt apply phase0.tfplan
terragrunt output -json > ../../data/spikes/terraform-outputs.json
cd ../..
uv run python infra/spikes/run.py
docker compose restart floci
docker compose up -d --wait
uv run python infra/spikes/run.py --verify-persistence
docker compose logs --tail=100 floci
docker compose down
```

The Homebrew/Colima commands are Mac prerequisites, run once if missing. Skip the plugin symlink if it already exists or Docker Desktop already supplies Compose. Colima is a free local Docker runtime; its VM and containers remain running until stopped. Use `colima stop` after stopping Compose if you want to release the VM's resources. This session installed these tools because they were missing.

On the Windows PC, install Ollama and run `ollama pull qwen3:8b` and `ollama pull embeddinggemma:300m`. For an offline local setup, change LLM_BACKEND and EMBEDDING_BACKEND to ollama in the Mac's .env, set OLLAMA_BASE_URL to the PC's reachable LAN URL, set EMBEDDING_DIMENSION to 768, and set VECTOR_TABLE to regulatory_chunks_ollama. Confirm the returned dimension on the first run. Configure the server's LAN listener and firewall before remote use. Mac Azure setup uses the .env.example selections and fills the endpoint, key, and chat deployment only in .env. Azure embeddings and chat are live-tested. The Ollama embedding and chat adapters are mock-tested only so far. Full remote-server instructions and live model verification belong to later phases.

The Bedrock embedding adapter implements Titan Text Embeddings v2 through boto3 InvokeModel. Set EMBEDDING_DIMENSION to 256, 512, or 1024 and use a separate VECTOR_TABLE such as regulatory_chunks_bedrock. The configured model ID lives in .env.example. This adapter is tested with boto3 Stubber, not real Bedrock. Floci's dummy responses cannot provide usable regulatory embeddings.

Direct Terraform equivalents, from infra/spikes: terraform init; terraform validate; terraform plan -out=phase0.tfplan; terraform apply phase0.tfplan; terraform output -json. Use one tool's workflow at a time. State is local in infra/spikes, ignored, never stored on real AWS. The spike wrapper explicitly selects Terraform rather than Terragrunt's possible OpenTofu default.

Terragrunt reads only endpoint and region from config.py using the root .env; it does not export secrets. Direct Terraform plan/apply require `-var='endpoint=<local endpoint>' -var='region=<configured region>'` from that configuration. The probe injects generated DATABASE_HOST and DATABASE_PORT into its Lambda environment; these are runtime outputs, not user configuration. The other database fields come from .env and are local-only credentials. Probe state, results JSON, and ZIP packages stay in ignored data/spikes.

Phase 1 commands: `uv run compliancelens ingest --download-only` records/downloads approved public documents without provider calls; `uv run compliancelens ingest --prepare-only` parses/chunks/redacts without vector writes or provider calls; `uv run compliancelens ingest` writes vectors and reuses unchanged hashes; `uv run compliancelens ingest --refresh` re-downloads before ingestion. `uv run pytest tests/test_store.py --db-integration` runs real PostgreSQL tests in temporary schemas; ordinary pytest skips them.

Presidio uses the pinned en_core_web_sm 3.8.0 official release wheel as a Python dependency. uv sync installs it; no runtime model downloads. Downloads validate official HTTPS hosts and redirects, consult robots.txt, limit size, and pause between requests. Retrieval timestamps are recorded in UTC.

Phase 2 command: `uv run compliancelens ask "question"` returns an answer/refusal, trusted citations, provider identity, and token usage as JSON, and writes a query UUID journal in ignored data/runs. `uv run pytest --db-integration` includes real retrieval tests. Evaluation remains planned: `uv run compliancelens eval`, unavailable until Phase 4.

## Code style

- Use type hints, small modules, clear names, and explicit dependencies. Prefer readable functions to heavy abstractions.
- No unnecessary comments, section banners, restatements, or commented-out code. A comment explains only a non-obvious reason and stays on one short line.
- Docstrings are only for public functions whose names and types do not explain their contract.
- Use plain prose without em dashes. Briefly explain unfamiliar Python and LangChain choices as they arise.
- Test core behavior and failure paths. Run the phase's checks before reporting it done.

## Secrets, privacy, and cost

- Secrets live only in ignored .env. .env.example contains empty Azure key and endpoint fields. No credential copying, key printing, SDK debug logging, or secrets in Terraform variables, state, Lambda bundles, reports, or git.
- AWS uses only dummy local credentials, explicit emulator endpoints, and no real account. Fail closed for spike endpoints outside loopback or the registered Compose host. Never mount host AWS credentials.
- Run a pre-commit secret scan using detect-secrets and Ruff. Disable scanner network verification. Hooks are defense in depth, not a guarantee. Floci dummy credentials and rejection-fixture lines have narrow inline allowlist pragmas; exact JSON sha256 checksum lines have an exclusion pattern. No source/manifest file is excluded wholesale.
- Azure replaces the original all-free inference requirement at the user's request. Phase 0 makes no Azure calls. Later Azure calls require PII redaction first, and context comes only from public regulatory documents. The Phase 1 Presidio boundary must remain on every embedding path; new chat/evaluation paths must redact before sending text.
- LLM_BACKEND accepts bedrock, ollama, azure; its code default is bedrock. EMBEDDING_BACKEND accepts the same values. .env.example selects azure for both on the Mac. Windows instructions select ollama for both and set the configured dimension to the observed embedding model dimension.
- Cap completion tokens (initial cap 2048), batch embeddings (initial batch size 16), disable hidden SDK retries for paid inference, and record input/output/embedding token usage by backend, model, and run. Token usage is not a dollar estimate without verified deployment pricing.
- Skip unchanged content hashes within the same embedding identity. Cache eval and judge responses on disk by a hash including the redacted prompt, backend, deployment/model, API version, and generation settings. Do not cache raw PII. The evaluation set stays at 30 to 40 questions.
- Every reported evaluation number must identify its backend, model, corpus, and run. A mock response is not an inference result. Real Bedrock remains untested unless the user explicitly changes the no-real-AWS constraint.
- Stop at every phase boundary. Check off only work actually verified. A blocked spike keeps Phase 0 in progress.

## Do not

- Do not create duplicate files or alternative names for the same thing.
- Do not hard-code application endpoints, credentials, model names, or vector dimensions.
- Do not add files outside this registry without updating this document first.
- Do not mix embedding models in a table or silently query an old index.
- Do not report a successful spike, evaluation score, safety guarantee, or Azure/Bedrock inference without evidence.
