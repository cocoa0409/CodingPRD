"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def employer_headers():
    return TEST_USERS["employer_headers"]


@pytest.fixture
def worker_headers():
    return TEST_USERS["worker_headers"]


@pytest.fixture
def verifier_headers():
    return TEST_USERS["verifier_headers"]