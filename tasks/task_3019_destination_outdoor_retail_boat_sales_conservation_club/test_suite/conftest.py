"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every individual test and injects
API_BASE_URL, so each test starts against an empty database.
"""
import pytest

from test_helpers import ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return api_client