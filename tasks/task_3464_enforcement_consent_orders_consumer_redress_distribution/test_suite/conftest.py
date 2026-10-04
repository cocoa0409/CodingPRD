"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; tests import
everything else straight from test_helpers. These fixtures are thin bridges
for tests that prefer fixture injection over direct imports.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def staff_attorney_headers():
    return TEST_USERS["staff_attorney_headers"]


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def compliance_monitor_headers():
    return TEST_USERS["compliance_monitor_headers"]


@pytest.fixture
def compliance_monitor_2_headers():
    return TEST_USERS["compliance_monitor_2_headers"]


@pytest.fixture
def fund_administrator_headers():
    return TEST_USERS["fund_administrator_headers"]


@pytest.fixture
def fund_administrator_2_headers():
    return TEST_USERS["fund_administrator_2_headers"]


@pytest.fixture
def disbursement_officer_headers():
    return TEST_USERS["disbursement_officer_headers"]


@pytest.fixture
def disbursement_officer_2_headers():
    return TEST_USERS["disbursement_officer_2_headers"]


@pytest.fixture
def company_representative_headers():
    return TEST_USERS["company_representative_headers"]


@pytest.fixture
def claimant_headers():
    return TEST_USERS["claimant_headers"]
