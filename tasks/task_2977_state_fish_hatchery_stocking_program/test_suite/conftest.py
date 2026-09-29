"""
Pytest fixtures for the State Fish Hatchery Stocking Program API test suite.

The runner restarts the service before every test, so each test begins against an
empty database and builds its own preconditions through the API. A fresh client
per test therefore avoids reusing a connection to a process that has gone away.
"""

import pytest

from test_helpers import ADMIN_HEADERS, ApiClient


@pytest.fixture
def api() -> ApiClient:
    """Client for the service under test, pointed at the runner's base URL."""
    return ApiClient()


@pytest.fixture
def admin():
    """`ProgramAdmin` headers: the statewide administrator, never station-scoped."""
    return ADMIN_HEADERS
