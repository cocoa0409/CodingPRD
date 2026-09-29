"""Shared pytest fixtures for the presort bureau API suite.

The harness restarts the server and empties the database before every single
test, so nothing may be shared across tests: each fixture below is function
scoped and each test builds the history it needs from an empty database.
"""

import pytest

from test_helpers import api_errors
from test_helpers.api_client import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client pointed at the server the harness started for this test."""
    api_errors.register_error_status_map()
    return ApiClient()
