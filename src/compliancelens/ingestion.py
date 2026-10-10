import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from compliancelens.config import Settings
from compliancelens.documents import Chunk, download_sources, make_chunks, parse_document
from compliancelens.embeddings import Embedder
from compliancelens.privacy import Redactor
from compliancelens.store import VectorStore, connect


def prepare_chunks(chunks: list[Chunk], redactor: Redactor) -> tuple[list[Chunk], dict[str, int]]:
    prepared, counts = [], Counter()
    for chunk in chunks:
        redacted = redactor.redact(chunk.text)
        counts.update(redacted.counts)
        prompt = embedding_text(replace(chunk, text=redacted.text))
        prompt = redactor.redact(prompt)
        counts.update(prompt.counts)
        if len(prompt.text.encode()) > 1900:
            raise ValueError(
                "Embedding text exceeds the conservative byte budget; lower CHUNK_SIZE_BYTES"
            )
        prepared.append(
            replace(
                chunk,
                text=redacted.text,
                content_hash=hashlib.sha256(prompt.text.encode()).hexdigest(),
            )
        )
    return prepared, dict(counts)


def embedding_text(chunk: Chunk) -> str:
    return f"Document: {chunk.document_title}\nSection: {chunk.section_heading}\n\n{chunk.text}"


def persist_chunks(
    prepared: dict[str, list[Chunk]],
    settings: Settings,
    embedder: Embedder,
    store: VectorStore,
    report: dict,
    save_report: Callable[[dict], None],
) -> None:
    unique = {chunk.content_hash: chunk for chunks in prepared.values() for chunk in chunks}
    vectors = store.cached_vectors(list(unique))
    pending = [chunk for key, chunk in unique.items() if key not in vectors]
    batch_size = settings.embedding_batch_size
    batches_needed = (len(pending) + batch_size - 1) // batch_size
    if batches_needed > settings.ingest_max_embedding_batches:
        raise ValueError(
            "Ingestion exceeds INGEST_MAX_EMBEDDING_BATCHES; review prepare-only first"
        )
    report["unique_embedding_inputs"] = len(unique)
    report["chunks_reused"] = report["total_chunks"] - len(pending)
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        result = embedder.embed([embedding_text(chunk) for chunk in batch])
        store.check_provider_model(result.provider_model)
        vectors.update(
            {
                chunk.content_hash: vector
                for chunk, vector in zip(batch, result.vectors, strict=True)
            }
        )
        report["embedding_batches"] += 1
        report["chunks_embedded"] += len(batch)
        report["usage_records"] = embedder.usage_records
        save_report(report)
    for document_id, chunks in prepared.items():
        store.replace_document(document_id, chunks, vectors)


def ingest(
    settings: Settings,
    root: Path,
    download_only: bool = False,
    prepare_only: bool = False,
    refresh: bool = False,
) -> dict:
    run_id = uuid4().hex
    report_path = root / "data" / "runs" / f"{run_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "backend": settings.embedding_backend,
        "dimension": settings.embedding_dimension,
        "documents": [],
        "embedding_requests": 0,
        "embedding_batches": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usage_records": [],
        "chunks_embedded": 0,
        "chunks_reused": 0,
        "report_file": str(report_path.relative_to(root)),
    }
    embedder = None
    connection = None
    try:
        sources = download_sources(root / "data" / "manifest.json", root / "data" / "raw", refresh)
        if download_only:
            report["documents"] = [{"document_id": item.document_id} for item in sources]
            report["status"] = "downloaded"
            return report
        redactor = Redactor(settings.pii_spacy_model)
        embedder = Embedder(settings, redactor)
        report["identity"] = asdict(embedder.identity)
        prepared: dict[str, list[Chunk]] = {}
        for source in sources:
            sections = parse_document(source, root / "data" / "raw")
            chunks, redactions = prepare_chunks(make_chunks(source, sections, settings), redactor)
            if not chunks:
                raise ValueError("Refusing to replace a document with zero parsed chunks")
            prepared[source.document_id] = chunks
            report["documents"].append(
                {
                    "document_id": source.document_id,
                    "sections": len(sections),
                    "chunks": len(chunks),
                    "redactions": redactions,
                }
            )
        report["total_chunks"] = sum(len(chunks) for chunks in prepared.values())
        if prepare_only:
            report["status"] = "prepared"
            return report
        connection = connect(settings)
        store = VectorStore(connection, settings.vector_table, embedder.identity)
        store.initialize()
        persist_chunks(
            prepared,
            settings,
            embedder,
            store,
            report,
            lambda value: report_path.write_text(json.dumps(value, indent=2) + "\n"),
        )
        store.remove_documents_except(list(prepared))
        report["stored_rows"] = store.row_count()
        report["status"] = "completed"
        return report
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        raise
    finally:
        if embedder:
            report["usage_records"] = list(embedder.usage_records)
            report["embedding_requests"] = sum(item["requests"] for item in embedder.usage_records)
            report["input_tokens"] = sum(
                item["input_tokens"] or 0 for item in embedder.usage_records
            )
            report["token_usage_complete"] = (
                all(item["input_tokens"] is not None for item in embedder.usage_records)
                and embedder.requests_started == report["embedding_requests"]
            )
            report["requests_without_reported_usage"] = (
                embedder.requests_started - report["embedding_requests"]
            )
            embedder.close()
        if connection:
            connection.close()
        report["finished_at"] = datetime.now(UTC).isoformat()
        report_path.write_text(json.dumps(report, indent=2) + "\n")
