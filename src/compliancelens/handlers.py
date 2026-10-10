import base64
import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from compliancelens.config import Settings
from compliancelens.documents import (
    Chunk,
    Section,
    Source,
    load_manifest,
    make_chunks,
    parse_document,
)
from compliancelens.embeddings import Embedder
from compliancelens.ingestion import persist_chunks, prepare_chunks
from compliancelens.privacy import Redactor
from compliancelens.rag import ask
from compliancelens.store import IdentityMismatch, VectorStore, connect

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "data" / "manifest.json").is_file():
    ROOT = ROOT.parent


class IngestionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    document_id: str
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    question: str


def runtime_settings() -> Settings:
    return Settings(_env_file="/run/compliancelens/.env")


def artifact_client(settings: Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_default_region,
        config=Config(retries={"max_attempts": 0}, s3={"addressing_style": "path"}),
    )


def trusted_event(event: dict) -> tuple[IngestionEvent, Source]:
    request = IngestionEvent.model_validate(event)
    UUID(request.run_id)
    _, sources = load_manifest(ROOT / "data" / "manifest.json")
    source = next((item for item in sources if item.document_id == request.document_id), None)
    if source is None or not source.sha256 or not source.retrieved_at:
        raise ValueError("Document must have verified public provenance in the bundled manifest")
    return request, source


def artifact_key(request: IngestionEvent, stage: str) -> str:
    return f"runs/{request.run_id}/{request.document_id}/{stage}.json"


def read_artifact(client: Any, bucket: str, key: str, limit: int = 20_000_000) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    try:
        content = response["Body"].read(limit + 1)
    finally:
        response["Body"].close()
    if len(content) > limit:
        raise ValueError("Artifact exceeds size limit")
    return content


def write_artifact(client: Any, bucket: str, key: str, value: dict) -> None:
    client.put_object(
        Bucket=bucket, Key=key, Body=json.dumps(value).encode(), ContentType="application/json"
    )


def parse_handler(event: dict, context: Any) -> dict:
    request, source = trusted_event(event)
    settings = runtime_settings()
    client = artifact_client(settings)
    content = read_artifact(
        client,
        settings.raw_bucket,
        f"documents/{source.document_id}/{source.sha256}.{source.format}",
    )
    with TemporaryDirectory() as directory:
        path = Path(directory)
        (path / f"{source.document_id}.{source.format}").write_bytes(content)
        sections = parse_document(source, path)
    write_artifact(
        client,
        settings.intermediate_bucket,
        artifact_key(request, "parsed"),
        {"source_sha256": source.sha256, "sections": [asdict(s) for s in sections]},
    )
    return request.model_dump()


def chunk_handler(event: dict, context: Any) -> dict:
    request, source = trusted_event(event)
    settings = runtime_settings()
    client = artifact_client(settings)
    parsed = json.loads(
        read_artifact(client, settings.intermediate_bucket, artifact_key(request, "parsed"))
    )
    if parsed["source_sha256"] != source.sha256:
        raise ValueError("Parsed artifact provenance mismatch")
    sections = [Section(**item) for item in parsed["sections"]]
    chunks, redactions = prepare_chunks(
        make_chunks(source, sections, settings), Redactor(settings.pii_spacy_model)
    )
    if not chunks:
        raise ValueError("Refusing zero parsed chunks")
    write_artifact(
        client,
        settings.intermediate_bucket,
        artifact_key(request, "chunks"),
        {
            "source_sha256": source.sha256,
            "chunks": [asdict(c) for c in chunks],
            "redactions": redactions,
        },
    )
    return request.model_dump()


def embed_handler(event: dict, context: Any) -> dict:
    request, source = trusted_event(event)
    settings = runtime_settings()
    client = artifact_client(settings)
    payload = json.loads(
        read_artifact(client, settings.intermediate_bucket, artifact_key(request, "chunks"))
    )
    if payload["source_sha256"] != source.sha256:
        raise ValueError("Chunk artifact provenance mismatch")
    chunks = [Chunk(**item) for item in payload["chunks"]]
    if not chunks or any(
        c.document_id != source.document_id
        or c.source_url != (source.resolved_url or source.source_url)
        or c.regulator != source.regulator
        or c.document_title != source.title
        or c.retrieved_at != source.retrieved_at
        for c in chunks
    ):
        raise ValueError("Chunk provenance differs from the public manifest")
    redactor = Redactor(settings.pii_spacy_model)
    prepared, _ = prepare_chunks(chunks, redactor)
    if any(
        a.content_hash != b.content_hash or a.text != b.text
        for a, b in zip(chunks, prepared, strict=True)
    ):
        raise ValueError("Chunk artifact redaction or hash mismatch")
    embedder = Embedder(settings, redactor)
    report = {
        "run_id": request.run_id,
        "document_id": request.document_id,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "identity": asdict(embedder.identity),
        "total_chunks": len(chunks),
        "embedding_batches": 0,
        "chunks_embedded": 0,
        "usage_records": [],
    }

    def save(value: dict) -> None:
        write_artifact(client, settings.intermediate_bucket, artifact_key(request, "usage"), value)

    try:
        with connect(settings) as connection:
            store = VectorStore(connection, settings.vector_table, embedder.identity)
            store.initialize()
            persist_chunks({source.document_id: chunks}, settings, embedder, store, report, save)
            report.update(status="completed", stored_rows=store.row_count())
        return {
            **request.model_dump(),
            "status": "completed",
            "usage_key": artifact_key(request, "usage"),
        }
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        raise RuntimeError("Ingestion failed; inspect the safe usage journal") from None
    finally:
        report.update(
            usage_records=embedder.usage_records,
            embedding_requests=embedder.requests_started,
            input_tokens=sum(i["input_tokens"] or 0 for i in embedder.usage_records),
            requests_without_reported_usage=embedder.requests_started
            - sum(i["requests"] for i in embedder.usage_records),
            finished_at=datetime.now(UTC).isoformat(),
        )
        save(report)
        embedder.close()


def response(status: int, value: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(value, default=str),
    }


def query_handler(event: dict, context: Any) -> dict:
    if event.get("httpMethod") != "POST":
        return response(405, {"error": "method_not_allowed"})
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return response(415, {"error": "unsupported_media_type"})
    try:
        body = event.get("body")
        if not isinstance(body, str) or len(body.encode()) > 16_000:
            raise ValueError("Invalid body")
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode()
        request = QueryRequest.model_validate_json(body)
        settings = runtime_settings()
        if (
            not request.question.strip()
            or len(request.question.encode()) > settings.query_max_bytes
        ):
            raise ValueError("Invalid question")
    except (ValueError, ValidationError):
        return response(400, {"error": "invalid_request"})
    try:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            shutil.copyfile(ROOT / "data" / "manifest.json", root / "data" / "manifest.json")
            try:
                result = ask(settings, root, request.question)
            finally:
                for path in (root / "data" / "runs").glob("*.json"):
                    write_artifact(
                        artifact_client(settings),
                        settings.intermediate_bucket,
                        f"runs/{path.stem}/query/report.json",
                        json.loads(path.read_text()),
                    )
        return response(200, result)
    except IdentityMismatch:
        return response(
            409,
            {
                "error": "index_identity_mismatch",
                "message": "Re-ingest into a separate VECTOR_TABLE or a fresh one.",
            },
        )
    except Exception:
        return response(502, {"error": "query_failed", "request_id": uuid4().hex})
