from dataclasses import replace
from uuid import uuid4

import pytest
from psycopg import sql

from compliancelens.config import Settings
from compliancelens.documents import Chunk
from compliancelens.embeddings import EmbeddingIdentity
from compliancelens.store import IdentityMismatch, VectorStore, connect


@pytest.fixture
def store(request: pytest.FixtureRequest):
    if not request.config.getoption("--db-integration"):
        pytest.skip("Use --db-integration for local PostgreSQL tests")
    connection = connect(Settings())
    schema = "test_" + uuid4().hex
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    connection.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
    identity = EmbeddingIdentity("azure", "test-deployment", 2, "test-fingerprint")
    store = VectorStore(connection, "test_chunks", identity)
    store.initialize()
    try:
        yield store
    finally:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        connection.close()


def chunk(identifier: str, content_hash: str = "hash") -> Chunk:
    return Chunk(
        identifier,
        "doc",
        content_hash,
        "Public text",
        "OSFI",
        "Guideline",
        "Governance",
        None,
        "governance",
        "https://www.osfi-bsif.gc.ca/en/test",
        "2026-10-08T12:00:00Z",
    )


def test_reingestion_reuses_hashes_and_removes_stale_chunks(store: VectorStore) -> None:
    store.replace_document(
        "doc", [chunk("a"), chunk("b", "other")], {"hash": [1.0, 0.0], "other": [0.0, 1.0]}
    )
    assert store.row_count() == 2
    cached = store.cached_vectors(["hash"])
    assert cached == {"hash": "[1,0]"}
    store.replace_document("doc", [replace(chunk("a"), section_heading="Updated heading")], cached)
    assert store.row_count() == 1
    assert store.cached_vectors(["other"]) == {}


@pytest.mark.parametrize(
    "change",
    [
        {"backend": "ollama"},
        {"model": "other"},
        {"dimension": 3},
        {"fingerprint": "new-policy"},
    ],
)
def test_changed_identity_refuses_reads_and_initialization(
    store: VectorStore, change: dict
) -> None:
    other = VectorStore(store.connection, "test_chunks", replace(store.identity, **change))
    with pytest.raises(IdentityMismatch, match="separate table"):
        other.initialize()
    with pytest.raises(IdentityMismatch, match="separate table"):
        other.cached_vectors(["hash"])


def test_provider_model_drift_is_rejected(store: VectorStore) -> None:
    store.check_provider_model("actual-model-v1")
    store.check_provider_model("actual-model-v1")
    with pytest.raises(IdentityMismatch, match="Provider model changed"):
        store.check_provider_model("actual-model-v2")


def test_removed_documents_are_pruned_after_success(store: VectorStore) -> None:
    store.replace_document("doc", [chunk("a")], {"hash": [1.0, 0.0]})
    other = replace(chunk("b"), document_id="removed")
    store.replace_document("removed", [other], {"hash": [1.0, 0.0]})
    store.remove_documents_except(["doc"])
    assert store.row_count() == 1
    with pytest.raises(ValueError, match="empty manifest"):
        store.remove_documents_except([])


def test_changed_hash_is_not_reused(store: VectorStore) -> None:
    store.replace_document(
        "doc", [chunk("a"), chunk("b", "unchanged")], {"hash": [1.0, 0.0], "unchanged": [0.0, 1.0]}
    )
    cached = store.cached_vectors(["changed", "unchanged"])
    assert set(cached) == {"unchanged"}
    store.replace_document(
        "doc", [chunk("a", "changed"), chunk("b", "unchanged")], {**cached, "changed": [0.5, 0.5]}
    )
    assert store.row_count() == 2
    assert store.cached_vectors(["hash"]) == {}
    assert set(store.cached_vectors(["changed", "unchanged"])) == {"changed", "unchanged"}


def test_failed_document_write_rolls_back_previous_rows(store: VectorStore) -> None:
    store.replace_document("doc", [chunk("a")], {"hash": [1.0, 0.0]})
    with pytest.raises(KeyError):
        store.replace_document(
            "doc", [chunk("new", "changed"), chunk("missing", "missing")], {"changed": [0.0, 1.0]}
        )
    assert store.row_count() == 1
    assert store.cached_vectors(["hash"]) == {"hash": "[1,0]"}


def test_retrieval_orders_by_cosine_and_preserves_citation_metadata(store: VectorStore) -> None:
    store.replace_document(
        "doc",
        [chunk("nearest"), chunk("other", "other")],
        {"hash": [1.0, 0.0], "other": [0.0, 1.0]},
    )
    results = store.search([1.0, 0.0], ["doc"], 2)
    assert [item.metadata["chunk_id"] for item in results] == ["nearest", "other"]
    assert results[0].metadata["similarity"] == pytest.approx(1.0)
    assert results[1].metadata["similarity"] == pytest.approx(0.0)
    assert results[0].metadata["section_heading"] == "Governance"
    assert results[0].page_content == "Public text"


def test_retrieval_excludes_documents_outside_manifest(store: VectorStore) -> None:
    store.replace_document("doc", [chunk("public")], {"hash": [0.5, 0.5]})
    private = replace(chunk("private", "private"), document_id="private")
    store.replace_document("private", [private], {"private": [1.0, 0.0]})
    assert [item.metadata["chunk_id"] for item in store.search([1.0, 0.0], ["doc"], 2)] == [
        "public"
    ]


def test_retrieval_refuses_different_embedding_identity(store: VectorStore) -> None:
    other = VectorStore(store.connection, "test_chunks", replace(store.identity, model="changed"))
    with pytest.raises(IdentityMismatch, match="separate table"):
        other.search([1.0, 0.0], ["doc"], 2)


def test_missing_index_identity_explains_reingestion(store: VectorStore) -> None:
    missing = VectorStore(store.connection, "missing_chunks", store.identity)
    with pytest.raises(IdentityMismatch, match="Re-ingest"):
        missing.search([1.0, 0.0], ["doc"], 2)
