import pytest
from pydantic import ValidationError

from compliancelens.config import Settings


@pytest.fixture
def values() -> dict[str, object]:
    return {
        "_env_file": None,
        "embedding_dimension": 1536,
        "aws_endpoint_url": "http://localhost:4566",
        "aws_default_region": "ca-central-1",
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",  # pragma: allowlist secret - test fixture
        "database_user": "test",
        "database_password": "test",  # pragma: allowlist secret - test fixture
        "database_name": "test",
    }


@pytest.mark.parametrize("backend", ["bedrock", "ollama", "azure"])
def test_backend_switches(values: dict[str, object], backend: str) -> None:
    settings = Settings(**values, llm_backend=backend, embedding_backend=backend)
    assert settings.llm_backend == backend
    assert settings.embedding_backend == backend


def test_code_default_is_bedrock(
    values: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("EMBEDDING_BACKEND", raising=False)
    settings = Settings(**values)
    assert settings.llm_backend == "bedrock"
    assert settings.embedding_backend == "bedrock"


@pytest.mark.parametrize("field", ["llm_backend", "embedding_backend"])
def test_unknown_backend_rejected(values: dict[str, object], field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**values, **{field: "unknown"})


@pytest.mark.parametrize("dimension", [0, -1, 2001])
def test_dimension_respects_hnsw_limit(values: dict[str, object], dimension: int) -> None:
    values["embedding_dimension"] = dimension
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("cap", [0, -1, 16385])
def test_output_cap_validated(values: dict[str, object], cap: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**values, llm_max_output_tokens=cap)


def test_secret_is_not_in_repr(values: dict[str, object]) -> None:
    settings = Settings(**values, azure_openai_api_key="private-value")
    assert "private-value" not in repr(settings)


def test_process_environment_overrides_env_file(
    values: dict[str, object], tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_BACKEND=azure\n")
    values["_env_file"] = env_file
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    assert Settings(**values).llm_backend == "ollama"


def test_example_has_unique_variables_and_mac_defaults() -> None:
    from pathlib import Path

    lines = Path(".env.example").read_text().splitlines()
    pairs = [line.split("=", 1) for line in lines if line and not line.startswith("#")]
    names = [name for name, _ in pairs]
    assert len(names) == len(set(names))
    values = dict(pairs)
    assert values["LLM_BACKEND"] == values["EMBEDDING_BACKEND"] == "azure"
    assert values["AZURE_OPENAI_API_KEY"] == ""
