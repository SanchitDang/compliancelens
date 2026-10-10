import hashlib
import json
from dataclasses import dataclass
from typing import Any

import boto3
import httpx
from botocore.config import Config
from openai import AzureOpenAI

from compliancelens.config import Settings
from compliancelens.privacy import Redactor


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    finish_reason: str
    complete: bool


class ChatBackend:
    def __init__(self, settings: Settings, redactor: Redactor, client: Any = None) -> None:
        self.settings = settings
        self.redactor = redactor
        self.client = client
        self.requests_started = 0
        self.usage_records: list[dict[str, Any]] = []
        self.model, endpoint, version = {
            "azure": (
                settings.azure_openai_deployment,
                settings.azure_openai_endpoint,
                settings.azure_openai_api_version,
            ),
            "ollama": (settings.ollama_chat_model, settings.ollama_base_url, "api/chat"),
            "bedrock": (settings.bedrock_chat_model, settings.aws_endpoint_url, "Converse"),
        }[settings.llm_backend]
        if not self.model or not endpoint or not version:
            raise ValueError("Selected chat backend needs its model, endpoint, and API settings")
        self.identity = {
            "backend": settings.llm_backend,
            "deployment": self.model,
            "api_version": version,
            "max_output_tokens": settings.llm_max_output_tokens,
            "query_redaction_policy": redactor.query_policy,
            "endpoint_fingerprint": hashlib.sha256(endpoint.rstrip("/").encode()).hexdigest(),
        }
        self.prompt_hash = ""

    def generate(self, system: str, user: str) -> ChatResult:
        system, user = (self.redactor.redact_query(text).text for text in (system, user))
        self.prompt_hash = hashlib.sha256(
            json.dumps({"system": system, "user": user, **self.identity}, sort_keys=True).encode()
        ).hexdigest()
        if self.settings.llm_backend == "azure":
            return self._azure(system, user)
        if self.settings.llm_backend == "ollama":
            return self._ollama(system, user)
        return self._bedrock(system, user)

    def _azure(self, system: str, user: str) -> ChatResult:
        if self.client is None:
            if not self.settings.azure_openai_api_key.get_secret_value():
                raise ValueError("Azure chat requires AZURE_OPENAI_API_KEY in .env")
            self.client = AzureOpenAI(
                azure_endpoint=self.settings.azure_openai_endpoint,
                api_key=self.settings.azure_openai_api_key.get_secret_value(),
                azure_deployment=self.model,
                api_version=self.settings.azure_openai_api_version,
                max_retries=0,
                timeout=120,
            )
        self.requests_started += 1
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_completion_tokens=self.settings.llm_max_output_tokens,
        )
        usage = response.usage
        details = getattr(usage, "completion_tokens_details", None)
        self.usage_records.append(
            {
                "model": response.model,
                "input_tokens": usage.prompt_tokens if usage else None,
                "output_tokens": usage.completion_tokens if usage else None,
                "reasoning_tokens": getattr(details, "reasoning_tokens", None),
            }
        )
        choice = response.choices[0] if response.choices else None
        return ChatResult(
            choice.message.content or "" if choice else "",
            response.model,
            choice.finish_reason if choice else "missing_choice",
            bool(choice and choice.finish_reason == "stop" and not choice.message.refusal),
        )

    def _ollama(self, system: str, user: str) -> ChatResult:
        if self.client is None:
            self.client = httpx.Client(base_url=self.settings.ollama_base_url, timeout=180)
        self.requests_started += 1
        response = self.client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": "json",
                "options": {"num_predict": self.settings.llm_max_output_tokens},
            },
        )
        response.raise_for_status()
        body = response.json()
        model = body.get("model", self.model)
        self.usage_records.append(
            {
                "model": model,
                "input_tokens": body.get("prompt_eval_count"),
                "output_tokens": body.get("eval_count"),
                "reasoning_tokens": None,
            }
        )
        reason = body.get("done_reason", "unknown")
        return ChatResult(
            body.get("message", {}).get("content", ""),
            model,
            reason,
            bool(body.get("done") and reason == "stop"),
        )

    def _bedrock(self, system: str, user: str) -> ChatResult:
        if self.client is None:
            self.client = boto3.client(
                "bedrock-runtime",
                endpoint_url=self.settings.aws_endpoint_url,
                region_name=self.settings.aws_default_region,
                aws_access_key_id=self.settings.aws_access_key_id,
                aws_secret_access_key=self.settings.aws_secret_access_key.get_secret_value(),
                config=Config(retries={"max_attempts": 0}, connect_timeout=5, read_timeout=120),
            )
        self.requests_started += 1
        body = self.client.converse(
            modelId=self.model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": self.settings.llm_max_output_tokens},
        )
        usage = body.get("usage", {})
        self.usage_records.append(
            {
                "model": self.model,
                "input_tokens": usage.get("inputTokens"),
                "output_tokens": usage.get("outputTokens"),
                "reasoning_tokens": None,
            }
        )
        text = "".join(
            item.get("text", "")
            for item in body.get("output", {}).get("message", {}).get("content", [])
        )
        reason = body.get("stopReason", "unknown")
        return ChatResult(text, self.model, reason, reason == "end_turn")

    def close(self) -> None:
        if self.client is not None and hasattr(self.client, "close"):
            self.client.close()
