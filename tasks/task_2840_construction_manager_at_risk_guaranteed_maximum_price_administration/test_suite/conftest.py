"""Shared fixtures for the CMAR guaranteed-maximum-price administration suite.

The server under test is relaunched before every test, so each test begins
against an empty store with the logical clock reading exactly
``2026-08-01T00:00:00Z``. Importing the helper package also registers the
error-identifier-to-HTTP-status map used by the framework validators.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A typed client bound to the freshly restarted server under test."""
    return ApiClient()


@pytest.fixture()
def api_client(api: ApiClient) -> ApiClient:
    """Alias for :func:`api`, for tests that read better with the longer name."""
    return api
