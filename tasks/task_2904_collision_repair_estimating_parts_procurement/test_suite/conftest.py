"""Suite-wide fixtures."""

import pytest

from test_helpers.api_client import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client pointed at the freshly restarted server for this test."""
    return ApiClient()
