"""Shared pytest fixtures.

The runner owns the server lifecycle and publishes its address in
``API_BASE_URL``; it restarts the server before every individual test, so each
test opens on an empty database and a logical clock reading
``2026-08-01T00:00:00.000Z``.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()
