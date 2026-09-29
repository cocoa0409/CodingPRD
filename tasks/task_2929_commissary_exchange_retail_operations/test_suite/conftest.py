"""Pytest bridge exposing the shared test infrastructure as fixtures.

The runner owns the server lifecycle: it restarts the application and empties
the database before every individual test, so nothing here starts, stops or
health-checks anything.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the API under test."""
    return api_client


@pytest.fixture(scope="session")
def users() -> dict:
    """Ready-made header dictionaries keyed by role."""
    return TEST_USERS
