"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def campaign_owner_headers():
    return TEST_USERS["campaign_owner_headers"]


@pytest.fixture
def backer_headers():
    return TEST_USERS["backer_headers"]


@pytest.fixture
def factory_coordinator_headers():
    return TEST_USERS["factory_coordinator_headers"]


@pytest.fixture
def freight_broker_headers():
    return TEST_USERS["freight_broker_headers"]


@pytest.fixture
def customs_agent_headers():
    return TEST_USERS["customs_agent_headers"]


@pytest.fixture
def fulfillment_operator_headers():
    return TEST_USERS["fulfillment_operator_headers"]


@pytest.fixture
def distributor_headers():
    return TEST_USERS["distributor_headers"]


@pytest.fixture
def localization_partner_headers():
    return TEST_USERS["localization_partner_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
