from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Backend = Literal["bedrock", "ollama", "azure"]


def require_local_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1", "floci"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AWS endpoint must be an HTTP loopback or Floci Compose endpoint")
    return endpoint.rstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    raw_bucket: str = ""
    intermediate_bucket: str = ""

    llm_backend: Backend = "bedrock"
    embedding_backend: Backend = "bedrock"
    embedding_dimension: int = Field(gt=0, le=2000)
    embedding_batch_size: int = Field(default=16, gt=0, le=128)
    llm_max_output_tokens: int = Field(default=2048, gt=0, le=16384)
    azure_openai_endpoint: str = ""
    azure_openai_api_key: SecretStr = SecretStr("")
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = ""
    azure_openai_embeddings_deployment: str = ""
    azure_openai_embeddings_api_version: str = ""
    ollama_base_url: str = ""
    ollama_chat_model: str = ""
    ollama_embedding_model: str = ""
    bedrock_chat_model: str = ""
    bedrock_embedding_model: str = ""
    aws_endpoint_url: str
    aws_default_region: str
    aws_access_key_id: str
    aws_secret_access_key: SecretStr
    database_user: str
    database_password: SecretStr
    database_name: str
    database_host: str = ""
    database_port: int = Field(default=0, ge=0, le=65535)
    vector_table: str = Field(default="", pattern=r"^([a-z][a-z0-9_]{0,39})?$")
    chunk_size_bytes: int = Field(default=1500, ge=256, le=4000)
    chunk_overlap_bytes: int = Field(default=200, ge=0)
    pii_spacy_model: str = ""
    ingest_max_embedding_batches: int = Field(default=40, ge=1, le=1000)
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    retrieval_min_similarity: float = Field(default=0.30, ge=0, le=1, allow_inf_nan=False)
    query_max_bytes: int = Field(default=2000, ge=100, le=8000)

    _local_aws_endpoint = field_validator("aws_endpoint_url")(require_local_endpoint)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        if self.chunk_overlap_bytes >= self.chunk_size_bytes:
            raise ValueError("CHUNK_OVERLAP_BYTES must be smaller than CHUNK_SIZE_BYTES")
        return self
