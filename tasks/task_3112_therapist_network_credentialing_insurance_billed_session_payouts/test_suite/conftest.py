"""Pytest fixtures exposing test_helpers infrastructure.

The runner starts and stops the server and injects API_BASE_URL; these fixtures
only hand the generated helpers to the tests.
"""
import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def payroll_service_headers():
    return TEST_USERS["payroll_service_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]