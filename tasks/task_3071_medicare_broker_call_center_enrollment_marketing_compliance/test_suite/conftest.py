"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def director_of_sales_headers():
    return TEST_USERS["director_of_sales_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def licensing_coordinator_headers():
    return TEST_USERS["licensing_coordinator_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def carrier_integration_headers():
    return TEST_USERS["carrier_integration_headers"]


@pytest.fixture
def licensed_agent_headers():
    """Fallback LicensedAgent header for calls that do not exercise ownership."""
    return TEST_USERS["licensed_agent_headers"]