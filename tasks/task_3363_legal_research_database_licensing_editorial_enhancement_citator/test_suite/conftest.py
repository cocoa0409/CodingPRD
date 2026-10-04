"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection and PYTHONPATH; every
test starts against a freshly restarted server with an empty database and the
logical clock at its startup default (PRD §2.4).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def content_ingester_headers():
    return TEST_USERS["content_ingester_headers"]


@pytest.fixture
def citator_analyst_headers():
    return TEST_USERS["citator_analyst_headers"]


@pytest.fixture
def attorney_editor_headers():
    return TEST_USERS["attorney_editor_headers"]


@pytest.fixture
def licensing_manager_headers():
    return TEST_USERS["licensing_manager_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
