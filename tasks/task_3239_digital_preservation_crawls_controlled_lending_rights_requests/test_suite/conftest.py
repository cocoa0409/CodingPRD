"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def library_admin_headers():
    return TEST_USERS["library_admin_headers"]


@pytest.fixture
def scan_operator_headers():
    return TEST_USERS["scan_operator_headers"]


@pytest.fixture
def crawl_operator_headers():
    return TEST_USERS["crawl_operator_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def accessibility_officer_headers():
    return TEST_USERS["accessibility_officer_headers"]


@pytest.fixture
def legal_reviewer_headers():
    return TEST_USERS["legal_reviewer_headers"]
