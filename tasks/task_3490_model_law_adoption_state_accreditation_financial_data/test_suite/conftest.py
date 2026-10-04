"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and restarts the API process before every
test, so each test starts against an empty store and the logical clock at its
pinned start instant. The client itself is stateless (base URL comes from the
runner-injected environment), so a session scope is safe.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, get_default_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Shared API client; server lifecycle is managed by the runner."""
    return get_default_client()


@pytest.fixture
def staff_headers():
    """AssociationStaff headers (opaque identity; safe as a shared constant)."""
    return TEST_USERS["association_staff_headers"]
