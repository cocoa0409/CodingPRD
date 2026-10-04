"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_consumer_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def referee_headers():
    return TEST_USERS["referee_headers"]


@pytest.fixture
def bureau_connector_headers():
    return TEST_USERS["bureau_connector_headers"]


@pytest.fixture
def lender_ops_headers():
    return TEST_USERS["lender_ops_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def data_protection_officer_headers():
    return TEST_USERS["data_protection_officer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def as_consumer():
    """Builder for ownership-gated consumer calls: as_consumer(consumer_id)."""
    return make_consumer_headers