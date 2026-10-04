"""Shared pytest wiring for the Cabinet Program Rollout suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public API.
The base URL is injected into the environment by the runner, so the client is
constructed with no arguments. Header constants and builders are imported
directly from ``test_helpers`` where the tests need them.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()
