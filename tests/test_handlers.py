import hashlib
import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from compliancelens import handlers
from compliancelens.documents import load_manifest
from compliancelens.store import IdentityMismatch


class Artifacts:
    def __init__(self):
        self.values = {}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.values[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, **options):
        self.values[(Bucket, Key)] = Body


@pytest.fixture
def runtime(monkeypatch):
    settings = SimpleNamespace(
        raw_bucket="raw", intermediate_bucket="intermediate", query_max_bytes=2000
    )
    monkeypatch.setattr(handlers, "runtime_settings", lambda: settings)
    return settings


def event(body, **changes):
    return {
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": body,
        **changes,
    }


@pytest.mark.parametrize(
    "body",
    [
        "{",
        "[]",
        "null",
        '{"question": 1}',
        '{"question": ""}',
        '{"question": "  "}',
        json.dumps({"question": "a" * 2001}),
        '{"question": "hello", "model": "override"}',
    ],
)
def test_invalid_queries_never_call_provider(body, runtime, monkeypatch):
    monkeypatch.setattr(handlers, "ask", lambda *args: pytest.fail("Provider boundary reached"))
    result = handlers.query_handler(event(body), None)
    assert result["statusCode"] == 400
    assert json.loads(result["body"]) == {"error": "invalid_request"}


def test_query_http_boundary(runtime):
    assert handlers.query_handler(event("{}", httpMethod="GET"), None)["statusCode"] == 405
    assert handlers.query_handler(event("{}", headers={}), None)["statusCode"] == 415
    assert handlers.query_handler(event("*", isBase64Encoded=True), None)["statusCode"] == 400
    assert handlers.query_handler(event("a" * 16001), None)["statusCode"] == 400


def test_query_preserves_safe_answer_and_journal(runtime, monkeypatch):
    artifacts = Artifacts()
    monkeypatch.setattr(handlers, "artifact_client", lambda settings: artifacts)

    def ask(settings, root, question):
        assert question == "What does the public guideline say?"
        report = {
            "status": "answered",
            "answer": "Public evidence [1]",
            "citations": [{"number": 1, "retrieved_at": datetime(2026, 10, 9, tzinfo=UTC)}],
        }
        path = root / "data" / "runs" / f"{uuid4().hex}.json"
        path.parent.mkdir()
        path.write_text(json.dumps(report, default=str))
        return report

    monkeypatch.setattr(handlers, "ask", ask)
    result = handlers.query_handler(
        event(json.dumps({"question": "What does the public guideline say?"})), None
    )
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["citations"][0]["retrieved_at"].startswith("2026-10-09")
    assert len(artifacts.values) == 1


@pytest.mark.parametrize(
    "error,status,code",
    [
        (IdentityMismatch("private detail"), 409, "index_identity_mismatch"),
        (RuntimeError("private detail"), 502, "query_failed"),
    ],
)
def test_query_error_does_not_echo_exception(error, status, code, runtime, monkeypatch):
    def fail(*args):
        raise error

    monkeypatch.setattr(handlers, "ask", fail)
    result = handlers.query_handler(event('{"question": "public"}'), None)
    assert result["statusCode"] == status
    assert json.loads(result["body"])["error"] == code
    assert "private" not in result["body"]


@pytest.mark.parametrize(
    "extra",
    [
        {"bucket": "other"},
        {"key": "untrusted"},
        {"document_id": "../private"},
        {"run_id": "../bad"},
    ],
)
def test_stages_reject_untrusted_event_before_aws(extra, monkeypatch):
    _, sources = load_manifest(handlers.ROOT / "data" / "manifest.json")
    request = {"document_id": sources[0].document_id, "run_id": uuid4().hex, **extra}
    monkeypatch.setattr(handlers, "artifact_client", lambda settings: pytest.fail("AWS reached"))
    with pytest.raises(ValueError):
        handlers.parse_handler(request, None)


def test_parse_checks_hash_and_keeps_only_artifact_reference(runtime, monkeypatch):
    _, sources = load_manifest(handlers.ROOT / "data" / "manifest.json")
    content = b"<main><h1>Public guideline</h1><p>Public requirements.</p></main>"
    source = sources[0].model_copy(update={"sha256": hashlib.sha256(content).hexdigest()})
    monkeypatch.setattr(
        handlers,
        "trusted_event",
        lambda value: (handlers.IngestionEvent.model_validate(value), source),
    )
    artifacts = Artifacts()
    key = ("raw", f"documents/{source.document_id}/{source.sha256}.{source.format}")
    artifacts.values[key] = b"tampered public document"
    monkeypatch.setattr(handlers, "artifact_client", lambda settings: artifacts)
    request = {"document_id": source.document_id, "run_id": uuid4().hex}
    with pytest.raises(ValueError, match="verified download"):
        handlers.parse_handler(request, None)
    assert len(artifacts.values) == 1
    artifacts.values[key] = content
    assert handlers.parse_handler(request, None) == request
    parsed = json.loads(
        artifacts.values[
            ("intermediate", handlers.artifact_key(handlers.IngestionEvent(**request), "parsed"))
        ]
    )
    assert parsed["sections"]
    assert parsed["source_sha256"] == source.sha256


@pytest.mark.parametrize(
    "handler,stage", [(handlers.chunk_handler, "parsed"), (handlers.embed_handler, "chunks")]
)
def test_intermediate_provenance_mismatch_fails_before_provider(
    handler, stage, runtime, monkeypatch
):
    _, sources = load_manifest(handlers.ROOT / "data" / "manifest.json")
    request = handlers.IngestionEvent(document_id=sources[0].document_id, run_id=uuid4().hex)
    artifacts = Artifacts()
    artifacts.values[("intermediate", handlers.artifact_key(request, stage))] = json.dumps(
        {"source_sha256": "tampered", "sections": [], "chunks": []}
    ).encode()
    monkeypatch.setattr(handlers, "artifact_client", lambda settings: artifacts)
    monkeypatch.setattr(handlers, "Embedder", lambda *args: pytest.fail("Provider reached"))
    with pytest.raises(ValueError, match="provenance mismatch"):
        handler(request.model_dump(), None)


def test_artifact_size_is_bounded():
    artifacts = Artifacts()
    artifacts.values[("raw", "key")] = b"x" * 11
    with pytest.raises(ValueError, match="size limit"):
        handlers.read_artifact(artifacts, "raw", "key", limit=10)
