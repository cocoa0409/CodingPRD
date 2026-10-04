"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before each test, so every test opens
against an empty store with the logical clock at its startup value.
"""

import pytest

from test_helpers import ApiClient, api_client


@pytest.fixture
def api() -> ApiClient:
    """API client; server lifecycle is managed by the runner."""
    return api_client
