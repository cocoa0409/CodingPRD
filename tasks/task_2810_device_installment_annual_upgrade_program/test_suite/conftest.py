"""Pytest fixtures exposing test_helpers infrastructure.

The runner puts the task root on PYTHONPATH, so `test_helpers` imports directly.
The server is killed and relaunched before every test, so each test observes an
empty database and a logical clock reading 2026-08-01T00:00:00Z.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    """Fallback Customer identity. Ownership-gated calls must instead use
    make_customer_headers(<the enrolled customer's id>)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def associate_headers():
    return TEST_USERS["associate_headers"]


@pytest.fixture
def associate_2_headers():
    return TEST_USERS["associate_2_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def underwriter_2_headers():
    return TEST_USERS["underwriter_2_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def technician_2_headers():
    return TEST_USERS["technician_2_headers"]


@pytest.fixture
def collections_headers():
    return TEST_USERS["collections_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
