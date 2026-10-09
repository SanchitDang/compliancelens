import pytest

from compliancelens.privacy import Redactor


@pytest.fixture(scope="module")
def redactor() -> Redactor:
    return Redactor("en_core_web_sm")


def test_initial_redaction_before_hosted_requests(redactor: Redactor) -> None:
    result = redactor.redact(
        "Jane Smith has SIN 123-456-789. Email jane@example.com or call 416-555-0100."
    )
    for value in ["Jane Smith", "123-456-789", "jane@example.com", "416-555-0100"]:
        assert value not in result.text
    assert set(result.counts) >= {"PERSON", "CA_SIN", "EMAIL_ADDRESS", "PHONE_NUMBER"}


def test_missing_local_model_fails_closed() -> None:
    with pytest.raises(ValueError, match="installed local model"):
        Redactor("missing_local_model")


def test_section_reference_is_not_redacted_as_an_ip(redactor: Redactor) -> None:
    result = redactor.redact("Refer to section 2.3.1.1. IP address 192.168.0.1 is sensitive.")
    assert "2.3.1.1" in result.text
    assert "192.168.0.1" not in result.text
