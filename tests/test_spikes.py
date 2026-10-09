import pytest

from compliancelens.config import require_local_endpoint


@pytest.mark.parametrize(
    "endpoint",
    ["http://localhost:4566", "http://127.0.0.1:4566/", "http://floci:4566", "http://[::1]:4566"],
)
def test_local_aws_endpoints_allowed(endpoint: str) -> None:
    assert require_local_endpoint(endpoint) == endpoint.rstrip("/")


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://s3.amazonaws.com",
        "http://localhost.evil.example:4566",
        "http://example.com:4566",
        "http://user:password@localhost:4566",  # pragma: allowlist secret - rejection fixture
        "http://localhost:4566/path",
        "http://localhost:4566?query=1",
        "http://localhost:4566#fragment",
    ],
)
def test_nonlocal_or_ambiguous_aws_endpoints_rejected(endpoint: str) -> None:
    with pytest.raises(ValueError):
        require_local_endpoint(endpoint)
