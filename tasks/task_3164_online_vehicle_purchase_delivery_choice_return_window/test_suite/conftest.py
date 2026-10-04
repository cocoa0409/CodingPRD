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
def customer_advocate_headers():
    return TEST_USERS["customer_advocate_headers"]


@pytest.fixture
def recon_operator_headers():
    return TEST_USERS["recon_operator_headers"]


@pytest.fixture
def registration_clerk_headers():
    return TEST_USERS["registration_clerk_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]
