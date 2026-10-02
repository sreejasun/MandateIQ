"""Autouse fixture forcing LLM_PROVIDER=mock for Dileep's test modules.

Kept out of tests/conftest.py on purpose: conftest.py is a shared file other teammates may
also create, which would cause a merge conflict. Import it in a test module with
    from tests.fixtures.mock_llm import force_mock_llm  # noqa: F401
"""
import pytest


@pytest.fixture(autouse=True)
def force_mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    yield
