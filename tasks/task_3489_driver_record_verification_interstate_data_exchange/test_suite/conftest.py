"""Pytest fixtures bridging the test helpers into the suite.

The runner restarts the API server before every test and exports
``API_BASE_URL``; the client is therefore built fresh per test through
``make_api_client`` (function scope) rather than shared at module level.
The base client reads the server URL from the environment.
"""

import pytest

from test_helpers import make_api_client


@pytest.fixture
def api():
    """A fresh API client per test; the server URL comes from API_BASE_URL."""
    return make_api_client()
