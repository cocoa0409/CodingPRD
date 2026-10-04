"""Pytest fixtures bridging the test_helpers infrastructure into pytest.

The runner owns the server lifecycle, per-test server restarts, API_BASE_URL
injection and PYTHONPATH; these fixtures only expose the generated helpers.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server itself is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    """Opaque PlatformAdmin identity (PRD §2.1)."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def verification_analyst_headers():
    """Opaque VerificationAnalyst identity (PRD §2.1)."""
    return TEST_USERS["verification_analyst_headers"]


@pytest.fixture
def emergency_manager_headers():
    """Opaque EmergencyManager identity (PRD §2.1)."""
    return TEST_USERS["emergency_manager_headers"]
