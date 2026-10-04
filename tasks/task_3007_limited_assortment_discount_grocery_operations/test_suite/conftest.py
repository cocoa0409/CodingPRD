"""Shared pytest wiring for the Limited-Assortment Grocery suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API. The base URL is injected into the environment by the runner.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()
