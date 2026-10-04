"""Pytest fixture bridge exposing test_helpers infrastructure.

The runner manages the server lifecycle and PYTHONPATH, so test_helpers is
importable without any sys.path manipulation.
"""
import pytest

from test_helpers import ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client