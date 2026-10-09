import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from compliancelens.config import Settings
from compliancelens.embeddings import EmbeddingIdentity
from compliancelens.ingestion import ingest


def test_failed_run_records_usage_without_echoing_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingEmbedder:
        identity = EmbeddingIdentity("azure", "test", 2, "test")
        usage_records = [{"input_tokens": 17, "requests": 1, "model": "test"}]
        requests_started = 1

        def __init__(self, *args) -> None:
            pass

        def embed(self, texts):
            raise RuntimeError("provider error contains raw input and a private value")

        def close(self) -> None:
            pass

    source = Mock(document_id="doc")
    chunk = Mock(content_hash="hash", document_title="Test", section_heading="Test", text="text")
    monkeypatch.setattr("compliancelens.ingestion.download_sources", lambda *args: [source])
    monkeypatch.setattr("compliancelens.ingestion.Redactor", Mock())
    monkeypatch.setattr("compliancelens.ingestion.Embedder", FailingEmbedder)
    monkeypatch.setattr("compliancelens.ingestion.parse_document", lambda *args: ["section"])
    monkeypatch.setattr("compliancelens.ingestion.make_chunks", lambda *args: [chunk])
    monkeypatch.setattr("compliancelens.ingestion.prepare_chunks", lambda *args: ([chunk], {}))
    monkeypatch.setattr("compliancelens.ingestion.connect", Mock())
    store = Mock()
    store.cached_vectors.return_value = {}
    monkeypatch.setattr("compliancelens.ingestion.VectorStore", lambda *args: store)
    settings = Settings(_env_file=".env.example")
    with pytest.raises(RuntimeError):
        ingest(settings, tmp_path)
    output = next((tmp_path / "data" / "runs").glob("*.json")).read_text()
    report = json.loads(output)
    assert report["status"] == "failed"
    assert report["input_tokens"] == 17
    assert "raw input" not in output
    assert "private value" not in output
    store.replace_document.assert_not_called()
