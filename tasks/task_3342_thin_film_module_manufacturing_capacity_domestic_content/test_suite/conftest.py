"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def contracts_officer_headers():
    return TEST_USERS["contracts_officer_headers"]


@pytest.fixture
def customer_admin_headers():
    return TEST_USERS["customer_admin_headers"]


@pytest.fixture
def supply_chain_auditor_headers():
    return TEST_USERS["supply_chain_auditor_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def warranty_administrator_headers():
    return TEST_USERS["warranty_administrator_headers"]


@pytest.fixture
def recycling_coordinator_headers():
    return TEST_USERS["recycling_coordinator_headers"]
