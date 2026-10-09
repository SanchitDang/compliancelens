import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import httpx
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from compliancelens.config import Settings
from compliancelens.embeddings import Embedder
from compliancelens.privacy import Redactor


@pytest.fixture(scope="module")
def redactor() -> Redactor:
    return Redactor("en_core_web_sm")


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=".env.example",
        **{
            "embedding_dimension": 2,
            "azure_openai_endpoint": "https://example.openai.azure.com",
            **overrides,
        },
    )


def response(vectors: list[list[float]]) -> SimpleNamespace:
    return SimpleNamespace(
        data=[SimpleNamespace(index=index, embedding=value) for index, value in enumerate(vectors)],
        usage=SimpleNamespace(prompt_tokens=17),
        model="text-embedding-3-small",
    )


def test_azure_batch_redacts_orders_vectors_and_records_usage(redactor: Redactor) -> None:
    client = Mock()
    result = response([[1.0, 0.0], [0.0, 1.0]])
    result.data.reverse()
    client.embeddings.create.return_value = result
    embedder = Embedder(settings(), redactor, client)
    batch = embedder.embed(["Email jane@example.com", "Keep public records"])
    arguments = client.embeddings.create.call_args.kwargs
    assert arguments["model"] == "text-embedding-3-small"
    assert len(arguments["input"]) == 2
    assert "jane@example.com" not in str(arguments)
    assert arguments["dimensions"] == 2
    assert batch.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert batch.input_tokens == 17


@pytest.mark.parametrize("vectors", [[[1.0]], [[float("nan"), 0]], [[0.0, 0.0]]])
def test_invalid_vectors_keep_billed_usage(redactor: Redactor, vectors: list) -> None:
    client = Mock()
    client.embeddings.create.return_value = response(vectors)
    embedder = Embedder(settings(), redactor, client)
    with pytest.raises(ValueError, match="invalid vectors"):
        embedder.embed(["Public regulatory text"])
    assert embedder.usage_records[0]["input_tokens"] == 17


def test_api_failure_does_not_claim_known_zero_usage(redactor: Redactor) -> None:
    client = Mock()
    client.embeddings.create.side_effect = TimeoutError()
    embedder = Embedder(settings(), redactor, client)
    with pytest.raises(TimeoutError):
        embedder.embed(["Public regulatory text"])
    assert embedder.requests_started == 1
    assert embedder.usage_records == []


def test_ollama_document_prompt_and_no_silent_truncation(redactor: Redactor) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]], "prompt_eval_count": 9})

    with httpx.Client(
        base_url="http://localhost:11434", transport=httpx.MockTransport(respond)
    ) as client:
        embedder = Embedder(settings(embedding_backend="ollama"), redactor, client)
        assert embedder.embed(["Public regulatory text"]).input_tokens == 9
    assert calls[0]["truncate"] is False
    assert calls[0]["input"][0].startswith("title: none | text:")


def test_bedrock_titan_v2_request_with_boto3_stubber(redactor: Redactor) -> None:
    config = settings(
        embedding_backend="bedrock",
        embedding_dimension=256,
        bedrock_embedding_model="amazon.titan-embed-text-v2:0",
    )
    client = boto3.client(
        "bedrock-runtime",
        endpoint_url=config.aws_endpoint_url,
        region_name=config.aws_default_region,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret - local stub
    )
    body = json.dumps({"embedding": [1.0] + [0.0] * 255, "inputTextTokenCount": 12}).encode()
    expected = {
        "modelId": config.bedrock_embedding_model,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(
            {
                "inputText": "Public regulatory text",
                "dimensions": 256,
                "normalize": True,
            }
        ),
    }
    with Stubber(client) as stub:
        stub.add_response(
            "invoke_model",
            {"body": StreamingBody(io.BytesIO(body), len(body)), "contentType": "application/json"},
            expected,
        )
        batch = Embedder(config, redactor, client).embed(["Public regulatory text"])
        assert len(batch.vectors[0]) == 256
        assert batch.input_tokens == 12
        stub.assert_no_pending_responses()


def test_endpoint_and_model_are_part_of_identity(redactor: Redactor) -> None:
    first = Embedder(settings(), redactor)
    second = Embedder(settings(azure_openai_endpoint="https://other.openai.azure.com"), redactor)
    assert first.identity.fingerprint != second.identity.fingerprint
