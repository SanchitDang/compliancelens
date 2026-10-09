import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--db-integration", action="store_true", default=False)
