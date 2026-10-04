"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; this module is a thin bridge
only. Each test starts against a freshly restarted server on an empty
database, so fixtures never assume carried-over state.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


@pytest.fixture
def facility_manager_headers() -> dict:
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def veterinarian_headers() -> dict:
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def iacuc_reviewer_headers() -> dict:
    return TEST_USERS["iacuc_reviewer_headers"]


@pytest.fixture
def customer_headers() -> dict:
    """Fallback Customer-role headers for non-ownership paths only. Any
    ownership-gated call must instead use make_customer_headers(customer_id)
    with the real Customer.id."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def logistics_headers() -> dict:
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def inspector_headers() -> dict:
    return TEST_USERS["inspector_headers"]
