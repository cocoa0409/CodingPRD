"""Shared pytest fixtures.

The harness restarts the API server before every individual test, so there is
no state to tear down between tests: each test bootstraps everything it needs
from an empty database.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server under test."""
    return ApiClient()
