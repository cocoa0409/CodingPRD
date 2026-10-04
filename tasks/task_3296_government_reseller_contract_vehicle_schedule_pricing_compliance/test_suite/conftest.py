"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def contracts_manager_headers():
    return TEST_USERS["contracts_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def reseller_ops_headers():
    return TEST_USERS["reseller_ops_headers"]


@pytest.fixture
def integrator_headers():
    return TEST_USERS["integrator_headers"]


@pytest.fixture
def finance_ops_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
