"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle (it restarts the server before every test) and
sets PYTHONPATH so `test_helpers` is importable without sys.path hacks.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return dict(TEST_USERS["admin_headers"])


@pytest.fixture
def verifier_headers():
    return dict(TEST_USERS["verifier_headers"])
