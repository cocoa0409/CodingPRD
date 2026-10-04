"""Shared pytest wiring for the Audit Independence Monitoring suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API. The base URL is injected into the environment by the runner, so the
client is constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient
from test_helpers import fixtures


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def reference(api: ApiClient):
    """An affiliate, an acting engagement partner, a client and an engagement."""
    return fixtures.seed_reference_data(api)
