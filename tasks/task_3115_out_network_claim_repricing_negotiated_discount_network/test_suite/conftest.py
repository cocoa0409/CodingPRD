"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def feed_operator_headers():
    return TEST_USERS["feed_operator_headers"]


@pytest.fixture
def idr_entity_headers():
    return TEST_USERS["idr_entity_headers"]


@pytest.fixture
def payer_admin_headers():
    return TEST_USERS["payer_admin_headers"]


@pytest.fixture
def payer_rep_headers():
    return TEST_USERS["payer_rep_headers"]


@pytest.fixture
def provider_rep_headers():
    return TEST_USERS["provider_rep_headers"]
