"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def licensing_specialist_headers():
    return TEST_USERS["licensing_specialist_headers"]


@pytest.fixture
def customer_admin_headers():
    # Shared fallback only; ownership-gated calls must use
    # test_helpers.make_customer_admin_headers(org["id"]).
    return TEST_USERS["customer_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
