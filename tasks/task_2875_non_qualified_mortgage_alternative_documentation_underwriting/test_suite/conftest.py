"""Shared pytest fixtures for the non-QM alt-doc underwriting suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client  # noqa: F401


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The stateless HTTP client. The harness restarts the server before every
    test, so each test begins against an empty database."""
    return api_client
