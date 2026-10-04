"""Pytest fixtures exposing the test_helpers infrastructure to the suite."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """Opaque CommissionAdmin headers (PRD section 2.1)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def staff_headers() -> dict:
    """Opaque CommissionStaff headers (PRD section 2.1)."""
    return TEST_USERS["staff_headers"]
