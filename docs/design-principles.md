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
tests/
  test_config.py                configuration validation tests
  test_spikes.py                local endpoint safety and spike checks
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
eval/
  questions.json                Phase 4 document-grounded questions
  results/                      Phase 4 publishable measured reports
  cache/                        ignored cached redacted eval and judge responses
docs/
  architecture.md               current and planned system, verified limits
  phases.md                     phase checklists, commands, status, deviations
  design-principles.md           this registry and conventions
  phase-0-results.md             commands, measured spike results, prerequisites
```

Only Phase 0 files are created now. Future files must be registered here first. No empty marker files or duplicate setup guides. Generated virtual environments, lockfiles, caches, and Terraform state belong at their tool-standard paths and are covered by .gitignore.

## Naming and ownership

- Work on the dev branch. Push changes to dev, open a pull request into main, and merge through that pull request. Do not commit feature work directly to main. The initial Phase 0 publication bootstraps main before dev is created.

- Python files, modules, functions, variables, tables, and columns use snake_case. Classes use PascalCase. Constants and environment variables use UPPER_SNAKE_CASE.
- Configuration lives only in config.py. Use typed settings. Never print settings or secret values. Env-file loading must not override explicit process variables.
- Each environment variable is assigned once in .env.example. Docs reference its name rather than maintaining a second full settings file. Windows instructions describe the necessary overrides.
- Terraform resources use descriptive snake_case labels. AWS names use compliancelens-{environment}-{purpose}. A Terraform locals block owns each name once; consumers use references or Terraform outputs.
- Phase 0 resource names are owned by infra/spikes/main.tf locals: raw_bucket = compliancelens-dev-spike-raw, sdk_bucket = compliancelens-dev-spike-sdk, database = compliancelens-dev-spike-db, lambda_function = compliancelens-dev-spike-query, lambda_role = compliancelens-dev-spike-lambda. run.py reads these values from terraform output JSON and must not invent replacements.
- The Compose service is floci. The shared network is compliancelens-local; storage volume is floci-data. These are owned by docker-compose.yml.
- The Phase 0 table is compliancelens_spike_chunks; its index is compliancelens_spike_chunks_embedding_hnsw. Both are owned by infra/spikes/run.py. Columns: id, content_hash, embedding_backend, embedding_model, embedding_dimension, embedding. It contains synthetic vectors, not real document embeddings.
- Phase 1 will register the production chunk table and its index identity before writing a schema. Backend, model/deployment identity, and dimension are immutable per table. Querying with a different identity fails with instructions to use a separate table or re-ingest into a fresh table. A same-sized vector is not proof of model compatibility.
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

On the Windows PC, install Ollama and run `ollama pull qwen3:8b` and `ollama pull embeddinggemma:300m`. For an offline local setup, change LLM_BACKEND and EMBEDDING_BACKEND to ollama in the Mac's .env, set OLLAMA_BASE_URL to the PC's reachable LAN URL, and set EMBEDDING_DIMENSION to 768 for EmbeddingGemma after confirming the returned dimension. Configure the server's LAN listener and firewall before remote use. Mac Azure setup uses the existing .env.example selections and fills the Azure endpoint, key, and chat deployment only in .env. No inference adapter exists in Phase 0, so these selections currently validate configuration only. Full remote-server instructions and live model verification belong to later phases.

Direct Terraform equivalents, from infra/spikes: terraform init; terraform validate; terraform plan -out=phase0.tfplan; terraform apply phase0.tfplan; terraform output -json. Use one tool's workflow at a time. State is local in infra/spikes, ignored, never stored on real AWS. The spike wrapper explicitly selects Terraform rather than Terragrunt's possible OpenTofu default.

Terragrunt reads only endpoint and region from config.py using the root .env; it does not export secrets. Direct Terraform plan/apply require `-var='endpoint=<local endpoint>' -var='region=<configured region>'` from that configuration. The probe injects generated DATABASE_HOST and DATABASE_PORT into its Lambda environment; these are runtime outputs, not user configuration. The other database fields come from .env and are local-only credentials. Probe state, results JSON, and ZIP packages stay in ignored data/spikes.

Ingest, ask, and eval commands do not exist in Phase 0. Their planned names are `uv run compliancelens ingest`, `uv run compliancelens ask "question"`, and `uv run compliancelens eval`. Register the exact arguments here when implemented. Do not present planned commands as working features.

## Code style

- Use type hints, small modules, clear names, and explicit dependencies. Prefer readable functions to heavy abstractions.
- No unnecessary comments, section banners, restatements, or commented-out code. A comment explains only a non-obvious reason and stays on one short line.
- Docstrings are only for public functions whose names and types do not explain their contract.
- Use plain prose without em dashes. Briefly explain unfamiliar Python and LangChain choices as they arise.
- Test core behavior and failure paths. Run the phase's checks before reporting it done.

## Secrets, privacy, and cost

- Secrets live only in ignored .env. .env.example contains empty Azure key and endpoint fields. No credential copying, key printing, SDK debug logging, or secrets in Terraform variables, state, Lambda bundles, reports, or git.
- AWS uses only dummy local credentials, explicit emulator endpoints, and no real account. Fail closed for spike endpoints outside loopback or the registered Compose host. Never mount host AWS credentials.
- Run a pre-commit secret scan using detect-secrets and Ruff. Scan files without displaying discovered secret values. Hooks are defense in depth, not a guarantee. Only the Floci dummy credential and rejection-fixture lines have narrow inline allowlist pragmas; do not exclude source files wholesale.
- Azure replaces the original all-free inference requirement at the user's request. Phase 0 makes no Azure calls. Later Azure calls require PII redaction first, and context comes only from public regulatory documents. Until the safety boundary exists, Azure text transmission remains disabled.
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
