import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from compliancelens.chat import ChatResult
from compliancelens.config import Settings
from compliancelens.documents import Source
from compliancelens.embeddings import EmbeddingBatch, EmbeddingIdentity
from compliancelens.privacy import Redactor
from compliancelens.rag import QueryEngine, ask, citation
from compliancelens.store import IdentityMismatch, VectorStore


@pytest.fixture(scope="module")
def redactor() -> Redactor:
    return Redactor("en_core_web_sm")


def document(similarity: float = 0.8) -> Document:
    return Document(
        page_content="Protect personal information using appropriate safeguards.",
        metadata={
            "chunk_id": "chunk",
            "document_id": "public-doc",
            "regulator": "OPC",
            "document_title": "Public guidance",
            "section_heading": "Safeguards",
            "page": None,
            "anchor": "safeguards",
            "source_url": "https://www.priv.gc.ca/en/test",
            "retrieved_at": "2026-10-08T12:00:00Z",
            "similarity": similarity,
        },
    )


def engine(
    redactor: Redactor, text: str, documents: list[Document] | None = None, complete: bool = True
) -> QueryEngine:
    settings = Settings(_env_file=".env.example")
    embedder = Mock()
    embedder.embed_query.return_value = EmbeddingBatch([[1, 0]], 7, 1, "embedding-model", 0)
    store, chat = Mock(spec=VectorStore), Mock()
    store.search.return_value = documents if documents is not None else [document()]
    chat.generate.return_value = ChatResult(
        text, "chat-model", "stop" if complete else "length", complete
    )
    source = Source(
        document_id="public-doc",
        regulator="OPC",
        title="Public guidance",
        source_url="https://www.priv.gc.ca/en/test",
        format="html",
        public=True,
    )
    return QueryEngine(settings, redactor, embedder, store, chat, [source])


def test_answer_builds_citations_from_provenance(redactor: Redactor) -> None:
    pipeline = engine(
        redactor,
        json.dumps(
            {
                "supported": True,
                "claims": [{"text": "Use appropriate safeguards.", "sources": [1, 1]}],
            }
        ),
    )
    result = pipeline.run("How should information be protected?")
    assert result["status"] == "answered"
    assert result["answer"] == "Use appropriate safeguards. [1]"
    assert result["citations"][0]["url"] == "https://www.priv.gc.ca/en/test#safeguards"
    assert result["citations"][0]["regulator"] == "OPC"
    assert pipeline.chat.generate.call_args.args[0].startswith("Answer questions")
    assert "Public excerpts" in pipeline.chat.generate.call_args.args[1]


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        '{"supported":true,"claims":[]}',
        '{"supported":true,"claims":[{"text":"Invented","sources":[2]}]}',
        '{"supported":true,"claims":[{"text":"Invented","sources":[0]}]}',
        '{"supported":true,"claims":[{"text":"Invented","sources":[]}]}',
        '{"supported":true,"claims":[{"text":"See https://evil.example","sources":[1]}]}',
        '{"supported":true,"claims":[{"text":"Claim [9]","sources":[1]}]}',
        '{"supported":false,"claims":[{"text":"Contradiction","sources":[1]}]}',
        '{"supported":true,"claims":[{"text":"Claim","sources":[true]}]}',
    ],
)
def test_invalid_output_is_withheld(redactor: Redactor, text: str) -> None:
    result = engine(redactor, text).run("Question")
    assert result["status"] == "refused"
    assert result["claims"] == result["citations"] == []


def test_weak_evidence_skips_chat(redactor: Redactor) -> None:
    pipeline = engine(redactor, "unused", [document(0.1)])
    assert pipeline.run("Out of scope question")["reason"] == "weak_evidence"
    pipeline.chat.generate.assert_not_called()


def test_model_abstention_for_unsupported_question(redactor: Redactor) -> None:
    result = engine(redactor, '{"supported":false,"claims":[]}').run("Unsupported")
    assert result["reason"] == "unsupported_by_context"


def test_incomplete_response_is_withheld(redactor: Redactor) -> None:
    result = engine(redactor, '{"supported":true', complete=False).run("Question")
    assert result["reason"] == "incomplete_or_filtered_output"
    assert result["finish_reason"] == "length"


def test_identity_mismatch_blocks_paid_embedding_and_chat(redactor: Redactor) -> None:
    pipeline = engine(redactor, "unused")
    pipeline.store.assert_identity.side_effect = IdentityMismatch("separate table")
    with pytest.raises(IdentityMismatch):
        pipeline.run("Question")
    pipeline.embedder.embed_query.assert_not_called()
    pipeline.chat.generate.assert_not_called()


def test_nonpublic_provenance_blocks_chat(redactor: Redactor) -> None:
    private = document()
    private.metadata["source_url"] = "https://private.example/document"
    pipeline = engine(redactor, "unused", [private])
    with pytest.raises(ValueError, match="public manifest"):
        pipeline.run("Question")
    pipeline.chat.generate.assert_not_called()


def test_pdf_citation_uses_one_based_page() -> None:
    doc = document()
    doc.metadata.update(page=4, anchor=None)
    assert citation(doc, 1)["url"].endswith("#page=4")


def test_query_failure_journal_redacts_question_and_omits_error_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import compliancelens.rag as rag

    settings = Settings(
        _env_file=".env.example",
        azure_openai_endpoint="https://example.azure.com",
        azure_openai_deployment="test-chat",
    )
    monkeypatch.setattr(rag, "load_manifest", lambda path: ({}, []))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manifest.json").write_text("{}")
    embedder, chat = Mock(), Mock()
    embedder.identity = EmbeddingIdentity("azure", "test", 1536, "fingerprint")
    embedder.usage_records = [{"input_tokens": 9, "requests": 1, "model": "test"}]
    embedder.requests_started = 1
    chat.identity = {"backend": "azure", "deployment": "test-chat"}
    chat.usage_records, chat.requests_started, chat.prompt_hash = [], 1, "hash"
    monkeypatch.setattr(rag, "Embedder", lambda *args: embedder)
    monkeypatch.setattr(rag, "ChatBackend", lambda *args: chat)
    connection = Mock()
    monkeypatch.setattr(rag, "connect", lambda *args: connection)
    pipeline = Mock()
    pipeline.run.side_effect = TimeoutError("jane@example.com echoed in error")
    monkeypatch.setattr(rag, "QueryEngine", lambda *args: pipeline)
    with pytest.raises(TimeoutError):
        ask(settings, tmp_path, "Question from jane@example.com")
    report_text = next((tmp_path / "data" / "runs").glob("*.json")).read_text()
    report = json.loads(report_text)
    assert "jane@example.com" not in report_text
    assert "jane@example.com" not in pipeline.run.call_args.args[0]
    assert report["embedding_usage"]["input_tokens"] == 9
    assert not report["chat_usage"]["token_usage_complete"]
    assert report["chat_usage"]["requests_without_reported_usage"] == 1
    assert report["error_type"] == "TimeoutError"
    connection.close.assert_called_once()


def test_oversize_question_never_creates_providers(tmp_path: Path) -> None:
    settings = Settings(_env_file=".env.example")
    with pytest.raises(ValueError, match="QUERY_MAX_BYTES"):
        ask(settings, tmp_path, "a" * 2001)
    report = json.loads(next((tmp_path / "data" / "runs").glob("*.json")).read_text())
    assert report["embedding_usage"]["requests_started"] == 0
