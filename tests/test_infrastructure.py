import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture
def provisioning():
    return load_module("infrastructure_settings", ROOT / "infra" / "settings.py")


def test_provisioning_never_exports_azure_keys_or_real_database_password(
    provisioning, monkeypatch
) -> None:
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "private-key")
    monkeypatch.setenv("DATABASE_PASSWORD", "private-database-password")
    monkeypatch.setattr(provisioning, "image_uri", lambda root: "example:local")
    values = provisioning.terraform_inputs(ROOT)
    assert set(values) == {
        "image_uri",
        "endpoint",
        "region",
        "database_user",
        "database_name",
        "database_password",
    }
    assert "private" not in json.dumps(values)


def test_provisioning_rejects_real_aws_endpoint(provisioning, monkeypatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://rds.ca-central-1.amazonaws.com")
    with pytest.raises(ValueError):
        provisioning.terraform_inputs(ROOT)


def test_query_scaffold_does_not_echo_input() -> None:
    scaffold = load_module(
        "scaffold_handler", ROOT / "infra" / "modules" / "platform" / "scaffold_handler.py"
    )
    result = scaffold.handler({"httpMethod": "POST", "body": "private question"}, None)
    assert result["statusCode"] == 501
    assert json.loads(result["body"])["status"] == "not_implemented"
    assert "private question" not in json.dumps(result)


def test_ingestion_scaffold_fails_explicitly() -> None:
    scaffold = load_module(
        "scaffold_handler", ROOT / "infra" / "modules" / "platform" / "scaffold_handler.py"
    )
    with pytest.raises(NotImplementedError):
        scaffold.handler({"bucket": "public", "key": "document"}, None)
