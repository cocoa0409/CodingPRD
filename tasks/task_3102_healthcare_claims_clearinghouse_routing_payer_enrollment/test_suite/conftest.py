"""Pytest wiring for the clearinghouse compliance suite.

The runner restarts the API server before each test and injects
``API_BASE_URL``; the client is constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()
