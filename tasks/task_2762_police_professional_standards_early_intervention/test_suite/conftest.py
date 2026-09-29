"""Shared pytest wiring for the Police Professional Standards & Early Intervention suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public API.
The base URL is injected into the environment by the runner, so the client is
constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient
from test_helpers import fixtures


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def world(api: ApiClient):
    """Standing reference data: two units, a room, four officers and every header set."""
    return fixtures.seed_reference_data(api)
