"""Shared pytest fixtures for the Hotel Franchise Conversion suite.

The harness restarts the API server before every individual test, so each
test observes an empty database.  No fixture here caches state across tests.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()
