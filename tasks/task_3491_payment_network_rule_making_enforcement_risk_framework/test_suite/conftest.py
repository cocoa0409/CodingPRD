"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle (restarted before every test) and
PYTHONPATH; tests import everything else from test_helpers directly.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, default_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return default_client


@pytest.fixture
def admin_headers() -> dict:
    """Primary PlatformAdmin headers (opaque identity)."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def admin_alt_headers() -> dict:
    """Alternate PlatformAdmin headers (segregation-of-duties counterpart)."""
    return TEST_USERS["platform_admin_alt_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    """Primary Auditor headers (opaque identity)."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_alt_headers() -> dict:
    """Alternate Auditor headers (segregation-of-duties counterpart)."""
    return TEST_USERS["auditor_alt_headers"]
