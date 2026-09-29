"""Fixtures shared by every test module in the suite."""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers import fixtures


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the server under test.

    The harness restarts the server before each test, so every test begins
    against an empty database and builds its own world through the API.
    """
    return ApiClient()


@pytest.fixture
def world(api: ApiClient):
    """A roster of licensees plus one cleanly sited disposal unit."""
    return fixtures.seed_reference_data(api)
