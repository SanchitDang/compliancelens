import json
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import httpx
import pytest
from botocore.stub import Stubber

from compliancelens.chat import ChatBackend
from compliancelens.config import Settings
from compliancelens.privacy import Redactor


@pytest.fixture(scope="module")
def redactor() -> Redactor:
    return Redactor("en_core_web_sm")


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=".env.example",
        **{
            "azure_openai_endpoint": "https://example.openai.azure.com",
            "azure_openai_deployment": "test-gpt5-deployment",
            **overrides,
        },
    )


def response(reason: str = "stop", refusal: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        model="gpt-5-test",
        usage=SimpleNamespace(
            prompt_tokens=23,
            completion_tokens=31,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=12),
        ),
        choices=[
            SimpleNamespace(
                finish_reason=reason,
                message=SimpleNamespace(content='{"supported":false,"claims":[]}', refusal=refusal),
            )
        ],
    )


def test_azure_request_redaction_cap_roles_and_usage(redactor: Redactor) -> None:
    client = Mock()
    client.chat.completions.create.return_value = response()
    backend = ChatBackend(settings(llm_max_output_tokens=512), redactor, client)
    result = backend.generate("Public guidance. Contact jane@example.com", "Jane Smith 123-456-789")
    arguments = client.chat.completions.create.call_args.kwargs
    assert set(arguments) == {"model", "messages", "max_completion_tokens"}
    assert arguments["model"] == "test-gpt5-deployment"
    assert arguments["max_completion_tokens"] == 512
    assert [item["role"] for item in arguments["messages"]] == ["system", "user"]
    assert all(
        value not in str(arguments) for value in ("jane@example.com", "Jane Smith", "123-456-789")
    )
    assert result.complete
    assert backend.usage_records == [
        {"model": "gpt-5-test", "input_tokens": 23, "output_tokens": 31, "reasoning_tokens": 12}
    ]
    assert len(backend.prompt_hash) == 64


@pytest.mark.parametrize(
    "reason,refusal",
    [("length", None), ("content_filter", None), ("stop", "Refused"), ("tool_calls", None)],
)
def test_azure_incomplete_filtered_refusal_and_tool_output(
    redactor: Redactor,
    reason: str,
    refusal: str | None,
) -> None:
    client = Mock()
    client.chat.completions.create.return_value = response(reason, refusal)
    backend = ChatBackend(settings(), redactor, client)
    assert not backend.generate("Rules", "Question").complete
    assert backend.usage_records[0]["output_tokens"] == 31


def test_azure_missing_usage_is_unknown(redactor: Redactor) -> None:
    client = Mock()
    result = response()
    result.usage = None
    client.chat.completions.create.return_value = result
    backend = ChatBackend(settings(), redactor, client)
    backend.generate("Rules", "Question")
    assert backend.usage_records[0]["input_tokens"] is None


def test_azure_does_not_retry_rejected_parameters(redactor: Redactor) -> None:
    client = Mock()
    client.chat.completions.create.side_effect = ValueError("Provider echoed private content")
    backend = ChatBackend(settings(), redactor, client)
    with pytest.raises(ValueError):
        backend.generate("Rules", "Question")
    assert client.chat.completions.create.call_count == 1
    assert backend.requests_started == 1
    assert backend.usage_records == []


def test_ollama_request_and_truncation(redactor: Redactor) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "done": True,
                "done_reason": "length",
                "message": {"content": "partial"},
                "prompt_eval_count": 12,
                "eval_count": 32,
            },
        )

    with httpx.Client(
        base_url="http://localhost:11434", transport=httpx.MockTransport(respond)
    ) as client:
        backend = ChatBackend(
            settings(llm_backend="ollama", llm_max_output_tokens=32), redactor, client
        )
        assert not backend.generate("Rules", "Question").complete
        assert backend.usage_records[0]["output_tokens"] == 32
    assert calls[0]["options"] == {"num_predict": 32}
    assert calls[0]["stream"] is False
    assert calls[0]["format"] == "json"


def test_bedrock_converse_contract_with_stubber(redactor: Redactor) -> None:
    config = settings(llm_backend="bedrock", bedrock_chat_model="test-bedrock-model")
    client = boto3.client(
        "bedrock-runtime",
        endpoint_url=config.aws_endpoint_url,
        region_name=config.aws_default_region,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret - local stub
    )
    expected = {
        "modelId": "test-bedrock-model",
        "system": [{"text": "Rules"}],
        "messages": [{"role": "user", "content": [{"text": "Question"}]}],
        "inferenceConfig": {"maxTokens": 2048},
    }
    body = {
        "output": {"message": {"role": "assistant", "content": [{"text": "answer"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
        "metrics": {"latencyMs": 8},
    }
    with Stubber(client) as stub:
        stub.add_response("converse", body, expected)
        backend = ChatBackend(config, redactor, client)
        result = backend.generate("Rules", "Question")
        assert result.complete and result.text == "answer"
        assert backend.usage_records[0]["input_tokens"] == 10
        stub.assert_no_pending_responses()
