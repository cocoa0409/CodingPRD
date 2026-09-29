"""Shared pytest fixtures for the Utility Service Line Warranty Program suite.

The harness restarts the API server before each individual test, so every test
starts against an empty store. Nothing is shared between tests but the client
object itself.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:10000")
