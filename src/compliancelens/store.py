from dataclasses import astuple
from typing import Any

import psycopg
from psycopg import sql

from compliancelens.config import Settings
from compliancelens.documents import Chunk
from compliancelens.embeddings import EmbeddingIdentity


class IdentityMismatch(ValueError):
    pass


def connect(settings: Settings) -> psycopg.Connection:
    if settings.database_host not in {"localhost", "127.0.0.1", "::1", "floci"}:
        raise ValueError("Phase 1 database must use the local Floci endpoint")
    if not settings.database_port:
        raise ValueError("Set DATABASE_PORT from the Floci RDS endpoint")
    return psycopg.connect(
        host=settings.database_host,
        port=settings.database_port,
        dbname=settings.database_name,
        user=settings.database_user,
        password=settings.database_password.get_secret_value(),
        connect_timeout=10,
        sslmode="disable",
        autocommit=True,
    )


class VectorStore:
    def __init__(
        self, connection: psycopg.Connection, table: str, identity: EmbeddingIdentity
    ) -> None:
        if not table or len(table) > 40 or not table.replace("_", "").isalnum():
            raise ValueError("VECTOR_TABLE must be a configured simple SQL identifier")
        self.connection = connection
        self.table = sql.Identifier(table)
        self.metadata = sql.Identifier(f"{table}_identity")
        self.index = sql.Identifier(f"{table}_embedding_hnsw")
        self.identity = identity

    def assert_identity(self) -> None:
        row = self.connection.execute(
            sql.SQL("SELECT backend, model, dimension, fingerprint FROM {}").format(self.metadata)
        ).fetchone()
        if row != astuple(self.identity):
            raise IdentityMismatch(
                "Embedding identity differs from this index. Set VECTOR_TABLE to a separate table "
                "and re-ingest, or explicitly rebuild a fresh table."
            )

    def initialize(self) -> None:
        with self.connection.transaction():
            self.connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            exists = self.connection.execute(
                "SELECT to_regclass(%s)", (self.table.as_string(self.connection),)
            ).fetchone()[0]
            metadata_exists = self.connection.execute(
                "SELECT to_regclass(%s)", (self.metadata.as_string(self.connection),)
            ).fetchone()[0]
            if exists or metadata_exists:
                if not (exists and metadata_exists):
                    raise IdentityMismatch(
                        "Existing table has no valid identity; use a fresh table"
                    )
                self.assert_identity()
                return
            self.connection.execute(
                sql.SQL(
                    "CREATE TABLE {} (backend text NOT NULL, model text NOT NULL, "
                    "dimension integer NOT NULL, fingerprint text NOT NULL UNIQUE, "
                    "provider_model text)"
                ).format(self.metadata)
            )
            self.connection.execute(
                sql.SQL("INSERT INTO {} VALUES (%s, %s, %s, %s, NULL)").format(self.metadata),
                astuple(self.identity),
            )
            self.connection.execute(
                sql.SQL(
                    "CREATE TABLE {} (id text PRIMARY KEY, document_id text NOT NULL, "
                    "content_hash text NOT NULL, text text NOT NULL, regulator text NOT NULL, "
                    "document_title text NOT NULL, section_heading text NOT NULL, page integer, "
                    "anchor text, source_url text NOT NULL, retrieved_at timestamptz NOT NULL, "
                    "embedding_backend text NOT NULL CHECK (embedding_backend = {}), "
                    "embedding_model text NOT NULL CHECK (embedding_model = {}), "
                    "embedding_dimension integer NOT NULL CHECK (embedding_dimension = {}), "
                    "embedding vector({}) NOT NULL)"
                ).format(
                    self.table,
                    sql.Literal(self.identity.backend),
                    sql.Literal(self.identity.model),
                    sql.Literal(self.identity.dimension),
                    sql.Literal(self.identity.dimension),
                )
            )
            self.connection.execute(
                sql.SQL("CREATE INDEX {} ON {} USING hnsw (embedding vector_cosine_ops)").format(
                    self.index, self.table
                )
            )

    def check_provider_model(self, model: str) -> None:
        with self.connection.transaction():
            current = self.connection.execute(
                sql.SQL("SELECT provider_model FROM {} FOR UPDATE").format(self.metadata)
            ).fetchone()[0]
            if current is not None and current != model:
                raise IdentityMismatch(
                    "Provider model changed behind the deployment; use a fresh table"
                )
            self.connection.execute(
                sql.SQL("UPDATE {} SET provider_model = %s").format(self.metadata), (model,)
            )

    def cached_vectors(self, hashes: list[str]) -> dict[str, str]:
        self.assert_identity()
        rows = self.connection.execute(
            sql.SQL(
                "SELECT content_hash, embedding::text FROM {} WHERE content_hash = ANY(%s)"
            ).format(self.table),
            (hashes,),
        ).fetchall()
        return dict(rows)

    def replace_document(
        self, document_id: str, chunks: list[Chunk], vectors: dict[str, Any]
    ) -> None:
        with self.connection.transaction():
            self.assert_identity()
            for chunk in chunks:
                vector = vectors[chunk.content_hash]
                if not isinstance(vector, str):
                    vector = "[" + ",".join(str(value) for value in vector) + "]"
                self.connection.execute(
                    sql.SQL(
                        "INSERT INTO {} VALUES "
                        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "content_hash=EXCLUDED.content_hash, text=EXCLUDED.text, "
                        "regulator=EXCLUDED.regulator, document_title=EXCLUDED.document_title, "
                        "section_heading=EXCLUDED.section_heading, page=EXCLUDED.page, "
                        "anchor=EXCLUDED.anchor, source_url=EXCLUDED.source_url, "
                        "retrieved_at=EXCLUDED.retrieved_at, embedding=EXCLUDED.embedding"
                    ).format(self.table),
                    (
                        *astuple(chunk),
                        self.identity.backend,
                        self.identity.model,
                        self.identity.dimension,
                        vector,
                    ),
                )
            self.connection.execute(
                sql.SQL("DELETE FROM {} WHERE document_id = %s AND NOT (id = ANY(%s))").format(
                    self.table
                ),
                (document_id, [chunk.id for chunk in chunks]),
            )

    def remove_documents_except(self, document_ids: list[str]) -> None:
        if not document_ids:
            raise ValueError("Refusing to clear an index from an empty manifest")
        with self.connection.transaction():
            self.assert_identity()
            self.connection.execute(
                sql.SQL("DELETE FROM {} WHERE NOT (document_id = ANY(%s))").format(self.table),
                (document_ids,),
            )

    def row_count(self) -> int:
        return self.connection.execute(
            sql.SQL("SELECT count(*) FROM {}").format(self.table)
        ).fetchone()[0]
