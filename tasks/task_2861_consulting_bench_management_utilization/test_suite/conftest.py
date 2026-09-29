"""Shared pytest fixtures for the Consulting Bench Management API suite.

The runner starts the API server, exports API_BASE_URL and relaunches the
server before every individual test, so each test sees an empty database.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server the runner started for this test."""
    return ApiClient()
