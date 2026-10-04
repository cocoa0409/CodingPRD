"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def seat_admin_headers():
    return TEST_USERS["seat_admin_headers"]


@pytest.fixture
def ats_service_headers():
    return TEST_USERS["ats_service_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
