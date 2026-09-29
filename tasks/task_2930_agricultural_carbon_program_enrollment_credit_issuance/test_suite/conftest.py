"""Shared pytest fixtures for the agricultural carbon programme suite.

The harness starts a fresh server for each test, so every fixture builds the
state it needs from an empty store through the documented endpoints.
"""

import pytest

# Importing the error catalogue registers the error_id → HTTP status mapping
# used by every ``validate_error`` call in the suite.
from test_helpers import api_errors  # noqa: F401
from test_helpers.api_client import ApiClient
from test_helpers.fixtures import Scenario


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def scenario(api: ApiClient) -> Scenario:
    """An empty scenario handle over the client."""
    return Scenario(api)
