"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def verifier_headers():
    return TEST_USERS["record_verifier_headers"]


@pytest.fixture
def hotline_headers():
    return TEST_USERS["hotline_operator_headers"]


@pytest.fixture
def fulfillment_headers():
    return TEST_USERS["fulfillment_agent_headers"]
