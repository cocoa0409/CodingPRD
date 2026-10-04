"""Pytest wiring for the teacher-classroom-funding suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API (see ``test_helpers.fixtures``). The base URL is injected into the
environment by the runner, so the client is constructed with no arguments.
"""

import pytest

from test_helpers import ADMIN_HEADERS, ANON_HEADERS, ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture()
def anon_headers():
    return ANON_HEADERS
