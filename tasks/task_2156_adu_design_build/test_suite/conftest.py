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
def design_lead_headers():
    return TEST_USERS["design_lead_headers"]


@pytest.fixture
def plan_checker_headers():
    return TEST_USERS["plan_checker_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def finance_advisor_headers():
    return TEST_USERS["finance_advisor_headers"]


@pytest.fixture
def homeowner_headers():
    """Shared Homeowner constant — only for calls that never reach an ownership check."""
    return TEST_USERS["homeowner_headers"]


@pytest.fixture
def building_inspector_headers():
    """Shared BuildingInspector constant — only for calls that never reach the
    assigned-inspector check."""
    return TEST_USERS["building_inspector_headers"]
