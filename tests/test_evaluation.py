import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from compliancelens.config import Settings
from compliancelens.embeddings import Embedder, EmbeddingBatch
from compliancelens.evaluation import (
    CachedChat,
    CachedEmbedder,
    Question,
    judge_answer,
    score,
    snapshot,
    usage,
    validate_questions,
)
from compliancelens.privacy import Redactor
from compliancelens.store import VectorStore


@pytest.fixture(scope="module")
def redactor() -> Redactor:
    return Redactor("en_core_web_sm")


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=".env.example",
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_deployment="test-deployment",
        **overrides,
    )


def client(text: str = '{"accurate":true,"citations":[]}') -> Mock:
    provider = Mock()
    provider.chat.completions.create.return_value = SimpleNamespace(
        model="test-model",
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5),
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=text, refusal=None)
            )
        ],
    )
    return provider


def test_chat_cache_redacts_and_reports_zero_new_usage(tmp_path, redactor) -> None:
    provider = client()
    backend = CachedChat(settings(), redactor, tmp_path, {"corpus": "one"}, client=provider)
    backend.generate("Rules", "Contact jane@example.com")
    before = snapshot(backend)
    result = backend.generate("Rules", "Contact jane@example.com")
    assert result.model == "test-model"
    assert provider.chat.completions.create.call_count == 1
    ledger = usage(backend, before)
    assert ledger["requests_started"] == ledger["input_tokens"] == ledger["output_tokens"] == 0
    assert ledger["cache_hits"] == 1
    assert backend.original_usage[0]["input_tokens"] == 20
    assert "jane@example.com" not in str(provider.chat.completions.create.call_args)
    assert all("jane@example.com" not in path.read_text() for path in tmp_path.iterdir())


@pytest.mark.parametrize("change", ["prompt", "corpus", "cap", "deployment", "api", "endpoint"])
def test_chat_cache_isolated_by_identity(tmp_path, redactor, change) -> None:
    provider = client()
    config = settings()
    scope = {"corpus": "one"}
    first = CachedChat(config, redactor, tmp_path, scope, client=provider)
    first.generate("Rules", "Question")
    updates = {
        "cap": {"llm_max_output_tokens": 32},
        "deployment": {"azure_openai_deployment": "other"},
        "api": {"azure_openai_api_version": "other"},
        "endpoint": {"azure_openai_endpoint": "https://other.openai.azure.com"},
    }
    config = config.model_copy(update=updates.get(change, {}))
    second = CachedChat(
        config,
        redactor,
        tmp_path,
        {"corpus": "two"} if change == "corpus" else scope,
        client=provider,
    )
    second.generate("Rules", "Other question" if change == "prompt" else "Question")
    assert provider.chat.completions.create.call_count == 2


@pytest.mark.parametrize("kind", ["pii", "incomplete", "corrupt", "refresh"])
def test_unsafe_incomplete_corrupt_or_refreshed_cache_is_not_reused(
    tmp_path, redactor, kind
) -> None:
    provider = client(
        "Contact jane@example.com" if kind == "pii" else '{"accurate":true,"citations":[]}'
    )
    if kind == "incomplete":
        provider.chat.completions.create.return_value.choices[0].finish_reason = "length"
    backend = CachedChat(settings(), redactor, tmp_path, {}, client=provider)
    backend.generate("Rules", "Question")
    if kind == "corrupt":
        next(tmp_path.iterdir()).write_text("invalid json")
    if kind == "refresh":
        backend.refresh = True
    backend.generate("Rules", "Question")
    assert provider.chat.completions.create.call_count == 2


def question(identifier: str = "q01", supported: bool = True) -> Question:
    return Question(
        id=identifier,
        question="What safeguards are needed?",
        supported=supported,
        facts=["Appropriate safeguards."] if supported else [],
        gold=[],
    )


def test_metrics_keep_failures_and_refusals_in_denominators() -> None:
    questions = [question(), question("q02"), question("q03", False)]
    outcomes = [
        {
            "id": "q01",
            "status": "answered",
            "accurate": True,
            "retrieval_hit": True,
            "citation_pairs": 2,
            "supported_pairs": 1,
        },
        {"id": "q02", "status": "failed", "citation_pairs": 1, "judge_missing": True},
        {"id": "q03", "status": "refused"},
    ]
    metrics = score(questions, outcomes)
    assert metrics["answer_accuracy"]["rate"] == 0.5
    assert metrics["retrieval_hit"]["rate"] == 0.5
    assert metrics["citation_correctness"]["rate"] == 1 / 3
    assert metrics["unsupported_refusal"]["rate"] == 1
    assert metrics["failed_questions"] == metrics["missing_judgments"] == 1
    assert score(questions, [])["answer_accuracy"]["denominator"] == 2
    assert score(questions, [])["citation_correctness"]["rate"] is None


def test_judge_requires_boolean_schema_and_exact_pair_count(tmp_path, redactor) -> None:
    provider = client('{"accurate":true,"citations":[]}')
    judge = CachedChat(settings(), redactor, tmp_path, {}, client=provider)
    answer = {"claims": [{"text": "Use safeguards.", "sources": [1]}]}
    with pytest.raises(ValueError):
        judge_answer(question(), answer, [Document(page_content="Use safeguards.")], judge)
    provider.chat.completions.create.return_value.choices[
        0
    ].message.content = '{"accurate":"yes","citations":[true]}'
    judge.refresh = True
    with pytest.raises(ValueError):
        judge_answer(question(), answer, [Document(page_content="Use safeguards.")], judge)


def test_unknown_provider_usage_is_preserved(tmp_path, redactor) -> None:
    provider = client()
    provider.chat.completions.create.side_effect = ValueError("Private provider error")
    backend = CachedChat(settings(), redactor, tmp_path, {}, client=provider)
    before = snapshot(backend)
    with pytest.raises(ValueError):
        backend.generate("Rules", "Question")
    ledger = usage(backend, before)
    assert ledger["requests_without_reported_usage"] == 1
    assert not ledger["token_usage_complete"]
    assert not list(tmp_path.iterdir())


def test_vector_cache_validates_dimension_and_provider(tmp_path, redactor, monkeypatch) -> None:
    config = settings(embedding_dimension=2)
    call = Mock(return_value=EmbeddingBatch([[1.0, 0.0]], 4, 1, "embedding-model", 0))
    monkeypatch.setattr(Embedder, "embed_query", call)
    first = CachedEmbedder(config, redactor, tmp_path, "embedding-model")
    first.embed_query("Question")
    second = CachedEmbedder(config, redactor, tmp_path, "embedding-model")
    assert second.embed_query("Question").vectors == [[1.0, 0.0]]
    assert call.call_count == 1
    path = next(tmp_path.iterdir())
    cached = json.loads(path.read_text())
    cached["vector"] = [1]
    path.write_text(json.dumps(cached))
    third = CachedEmbedder(config, redactor, tmp_path, "embedding-model")
    third.embed_query("Question")
    assert call.call_count == 2
    changed = CachedEmbedder(config, redactor, tmp_path, "different-model")
    with pytest.raises(ValueError):
        changed.embed_query("Question")


def test_benchmark_rejects_duplicate_ids_and_changed_gold_before_inference(
    tmp_path, redactor
) -> None:
    body = json.loads(Path("eval/questions.json").read_text())
    path = tmp_path / "questions.json"
    body["questions"][1]["id"] = body["questions"][0]["id"]
    path.write_text(json.dumps(body))
    store = Mock(spec=VectorStore)
    store.connection = Mock()
    store.table = Mock()
    with pytest.raises(ValueError, match="unique"):
        validate_questions(path, store, [], settings())
    assert not store.connection.execute.called
    body["questions"][1]["id"] = "q02"
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="Gold reference"):
        validate_questions(path, store, [], settings())


def test_benchmark_contains_34_questions_and_ten_public_documents() -> None:
    questions = [
        Question.model_validate(q)
        for q in json.loads(Path("eval/questions.json").read_text())["questions"]
    ]
    assert len(questions) == 34
    assert sum(q.supported for q in questions) == 30
    assert len({g.document_id for q in questions for g in q.gold}) == 10


def test_judge_accepts_every_numbered_pair_in_order(tmp_path, redactor) -> None:
    provider = client(
        '{"accurate":true,"citations":[{"pair":1,"supported":true},{"pair":2,"supported":false}]}'
    )
    judge = CachedChat(settings(), redactor, tmp_path, {}, client=provider)
    answer = {"claims": [{"text": "Use safeguards.", "sources": [1, 2]}]}
    documents = [Document(page_content="Use safeguards."), Document(page_content="Review risks.")]
    judgment = judge_answer(question(), answer, documents, judge)
    assert judgment.accurate
    assert [item.supported for item in judgment.citations] == [True, False]
    sent = json.loads(provider.chat.completions.create.call_args.kwargs["messages"][1]["content"])
    assert sent["required_citation_decisions"] == 2
    assert [pair["pair"] for pair in sent["pairs"]] == [1, 2]
    assert "sources" not in str(sent["answer_claims"])


def test_judge_rejects_duplicated_pair_ids(tmp_path, redactor) -> None:
    provider = client(
        '{"accurate":true,"citations":[{"pair":1,"supported":true},{"pair":1,"supported":true}]}'
    )
    judge = CachedChat(settings(), redactor, tmp_path, {}, client=provider)
    with pytest.raises(ValueError, match="count"):
        judge_answer(
            question(),
            {"claims": [{"text": "Use safeguards.", "sources": [1, 2]}]},
            [Document(page_content="Use safeguards.")] * 2,
            judge,
        )


def test_cache_checks_decoded_json_fields(tmp_path, redactor) -> None:
    encoded = r'{"claims":[{"text":"jane\u0040example.com"}]}'
    assert redactor.redact_query(encoded).text == encoded
    provider = client(encoded)
    backend = CachedChat(settings(), redactor, tmp_path, {}, client=provider)
    backend.generate("Rules", "Question")
    assert not list(tmp_path.iterdir())


def test_cached_original_tokens_are_separate_from_new_usage(tmp_path, redactor) -> None:
    provider = client()
    backend = CachedChat(settings(), redactor, tmp_path, {}, client=provider)
    backend.generate("Rules", "Question")
    before = snapshot(backend)
    backend.generate("Rules", "Question")
    ledger = usage(backend, before)
    assert ledger["input_tokens"] == ledger["output_tokens"] == 0
    assert ledger["cached_response_original_tokens"] == {"input_tokens": 20, "output_tokens": 5}


def test_identity_failure_journals_safe_error_before_provider_calls(
    tmp_path, redactor, monkeypatch
) -> None:
    import compliancelens.evaluation as evaluation
    from compliancelens.store import IdentityMismatch

    connection = Mock()
    store = Mock(spec=VectorStore)
    store.assert_identity.side_effect = IdentityMismatch("private diagnostic")
    monkeypatch.setattr(evaluation, "Redactor", lambda model: redactor)
    monkeypatch.setattr(evaluation, "load_manifest", lambda path: ({}, []))
    monkeypatch.setattr(evaluation, "connect", lambda config: connection)
    monkeypatch.setattr(evaluation, "VectorStore", lambda *arguments: store)
    chat = Mock()
    monkeypatch.setattr(evaluation, "CachedChat", chat)
    with pytest.raises(IdentityMismatch):
        evaluation.evaluate(settings(), tmp_path)
    path = next((tmp_path / "data" / "runs").glob("*.json"))
    report = json.loads(path.read_text())
    assert report["status"] == "failed"
    assert report["error_type"] == "IdentityMismatch"
    assert "private diagnostic" not in path.read_text()
    assert not chat.called
    connection.close.assert_called_once()
