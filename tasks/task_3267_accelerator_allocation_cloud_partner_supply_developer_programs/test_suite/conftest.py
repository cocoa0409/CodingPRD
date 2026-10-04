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
def supply_planner_headers():
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def partner_program_manager_headers():
    return TEST_USERS["partner_program_manager_headers"]


@pytest.fixture
def support_account_manager_headers():
    return TEST_USERS["support_account_manager_headers"]


@pytest.fixture
def supply_compliance_officer_headers():
    return TEST_USERS["supply_compliance_officer_headers"]


@pytest.fixture
def lifecycle_program_manager_headers():
    return TEST_USERS["lifecycle_program_manager_headers"]


@pytest.fixture
def partner_ops_headers():
    return TEST_USERS["partner_ops_headers"]