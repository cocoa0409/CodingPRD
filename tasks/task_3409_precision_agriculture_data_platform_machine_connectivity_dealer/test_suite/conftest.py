"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; the client
below is a stateless HTTP facade, so a session-scoped instance is safe even
though the server restarts before every test.
"""

import pytest

from test_helpers import ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client
