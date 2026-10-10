import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import boto3
import httpx
from botocore.config import Config
from openai import AzureOpenAI

from compliancelens.config import Settings
from compliancelens.privacy import Redactor


@dataclass(frozen=True)
class EmbeddingIdentity:
    backend: str
    model: str
    dimension: int
    fingerprint: str


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    input_tokens: int | None
    requests: int
    provider_model: str
    redactions: int


class Embedder:
    def __init__(self, settings: Settings, redactor: Redactor, client: Any = None) -> None:
        self.settings = settings
        self.redactor = redactor
        self.client = client
        self.usage_records: list[dict[str, Any]] = []
        self.requests_started = 0
        backend = settings.embedding_backend
        model, endpoint, version = {
            "azure": (
                settings.azure_openai_embeddings_deployment,
                settings.azure_openai_endpoint,
                settings.azure_openai_embeddings_api_version,
            ),
            "ollama": (settings.ollama_embedding_model, settings.ollama_base_url, "api/embed"),
            "bedrock": (settings.bedrock_embedding_model, settings.aws_endpoint_url, "InvokeModel"),
        }[backend]
        if not model or not endpoint or not version:
            raise ValueError(
                "Selected embedding backend needs its model, endpoint, and API settings"
            )
        identity = {
            "backend": backend,
            "model": model,
            "dimension": settings.embedding_dimension,
            "endpoint": endpoint.rstrip("/"),
            "api_version": version,
            "redaction": redactor.policy,
            "nlp_model": settings.pii_spacy_model,
            "prompt_policy": "document-title-section-v1",
        }
        self.identity = EmbeddingIdentity(
            backend,
            model,
            settings.embedding_dimension,
            hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
        )

    def embed_query(self, text: str) -> EmbeddingBatch:
        return self.embed([text], query=True)

    def embed(self, texts: list[str], *, query: bool = False) -> EmbeddingBatch:
        if not texts or len(texts) > self.settings.embedding_batch_size:
            raise ValueError("Embedding input must be a nonempty configured-size batch")
        redact = self.redactor.redact_query if query else self.redactor.redact
        redacted = [redact(text) for text in texts]
        safe_texts = [item.text for item in redacted]
        redactions = sum(sum(item.counts.values()) for item in redacted)
        if self.identity.backend == "azure":
            result = self._azure(safe_texts, redactions)
        elif self.identity.backend == "ollama":
            result = self._ollama(safe_texts, redactions, query)
        else:
            result = self._bedrock(safe_texts, redactions)
        if len(result.vectors) != len(texts):
            raise ValueError("Embedding provider returned the wrong number of vectors")
        if any(
            len(vector) != self.identity.dimension
            or any(not math.isfinite(value) for value in vector)
            or not any(value != 0 for value in vector)
            for vector in result.vectors
        ):
            raise ValueError(
                "Provider returned invalid vectors or a different configured dimension"
            )
        return result

    def _azure(self, texts: list[str], redactions: int) -> EmbeddingBatch:
        if not self.client:
            if not self.settings.azure_openai_api_key.get_secret_value():
                raise ValueError("Azure embeddings require AZURE_OPENAI_API_KEY in .env")
            self.client = AzureOpenAI(
                azure_endpoint=self.settings.azure_openai_endpoint,
                api_key=self.settings.azure_openai_api_key.get_secret_value(),
                azure_deployment=self.identity.model,
                api_version=self.settings.azure_openai_embeddings_api_version,
                max_retries=0,
                timeout=60,
            )
        self.requests_started += 1
        response = self.client.embeddings.create(
            model=self.identity.model,
            input=texts,
            dimensions=self.identity.dimension,
            encoding_format="float",
        )
        self.usage_records.append(
            {"input_tokens": response.usage.prompt_tokens, "requests": 1, "model": response.model}
        )
        entries = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in entries] != list(range(len(texts))):
            raise ValueError("Azure returned missing or duplicate embedding indexes")
        return EmbeddingBatch(
            [item.embedding for item in entries],
            response.usage.prompt_tokens,
            1,
            response.model,
            redactions,
        )

    def _ollama(self, texts: list[str], redactions: int, query: bool) -> EmbeddingBatch:
        if not self.client:
            self.client = httpx.Client(base_url=self.settings.ollama_base_url, timeout=180)
        self.requests_started += 1
        response = self.client.post(
            "/api/embed",
            json={
                "model": self.identity.model,
                "input": [
                    f"task: search result | query: {text}"
                    if query
                    else f"title: none | text: {text}"
                    for text in texts
                ],
                "truncate": False,
            },
        )
        response.raise_for_status()
        result = response.json()
        self.usage_records.append(
            {
                "input_tokens": result.get("prompt_eval_count"),
                "requests": 1,
                "model": result.get("model", self.identity.model),
            }
        )
        return EmbeddingBatch(
            result["embeddings"],
            result.get("prompt_eval_count"),
            1,
            result.get("model", self.identity.model),
            redactions,
        )

    def _bedrock(self, texts: list[str], redactions: int) -> EmbeddingBatch:
        if self.identity.dimension not in {256, 512, 1024}:
            raise ValueError(
                "Titan v2 embeddings need dimension 256, 512, or 1024 in a fresh table"
            )
        if not self.client:
            self.client = boto3.client(
                "bedrock-runtime",
                endpoint_url=self.settings.aws_endpoint_url,
                region_name=self.settings.aws_default_region,
                aws_access_key_id=self.settings.aws_access_key_id,
                aws_secret_access_key=self.settings.aws_secret_access_key.get_secret_value(),
                config=Config(retries={"max_attempts": 0}, connect_timeout=5, read_timeout=60),
            )
        vectors, tokens = [], 0
        for text in texts:
            self.requests_started += 1
            response = self.client.invoke_model(
                modelId=self.identity.model,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(
                    {"inputText": text, "dimensions": self.identity.dimension, "normalize": True}
                ),
            )
            result = json.loads(response["body"].read())
            self.usage_records.append(
                {
                    "input_tokens": result.get("inputTextTokenCount"),
                    "requests": 1,
                    "model": self.identity.model,
                }
            )
            vectors.append(result["embedding"])
            tokens += result["inputTextTokenCount"]
        return EmbeddingBatch(vectors, tokens, len(texts), self.identity.model, redactions)

    def close(self) -> None:
        if self.client and hasattr(self.client, "close"):
            self.client.close()
