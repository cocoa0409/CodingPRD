"""Shared fixtures for the electric-motor manufacturing compliance suite.

The runner owns the server lifecycle and gives every individual test an empty
database, so each test rebuilds the plant state it needs from scratch through
the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, Plant  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def plant(api: ApiClient) -> Plant:
    """An empty plant driver; the test drives it to the stage it needs."""
    return Plant(api)
