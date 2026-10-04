"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["pm_headers"]


@pytest.fixture
def acct_headers():
    return TEST_USERS["acct_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def risk_headers():
    return TEST_USERS["risk_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
