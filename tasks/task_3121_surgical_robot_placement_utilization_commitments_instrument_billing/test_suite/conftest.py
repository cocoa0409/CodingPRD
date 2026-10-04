"""Pytest fixtures exposing `test_helpers` infrastructure.

Server lifecycle is owned by prd-bench-local-runner, which restarts the API before
every individual test, so each test starts against an empty database.
"""

import pytest

from test_helpers import ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client