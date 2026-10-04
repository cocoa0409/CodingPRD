"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def administrator_headers():
    return TEST_USERS["administrator_headers"]


@pytest.fixture
def fundraising_manager_headers():
    return TEST_USERS["fundraising_manager_headers"]


@pytest.fixture
def payment_processor_headers():
    return TEST_USERS["payment_processor_headers"]


@pytest.fixture
def grant_administrator_headers():
    return TEST_USERS["grant_administrator_headers"]


@pytest.fixture
def grant_reviewer_headers():
    return TEST_USERS["grant_reviewer_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
