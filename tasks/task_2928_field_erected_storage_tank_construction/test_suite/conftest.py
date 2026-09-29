"""Pytest fixtures for the Field-Erected Storage Tank Construction API suite.

The server is restarted and its store is empty before every single test, so
each test builds every row it needs from scratch and no test depends on another.
"""

import pytest

from test_helpers.api_client import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A fresh client per test; the server lifecycle is the runner's concern."""
    return ApiClient()
