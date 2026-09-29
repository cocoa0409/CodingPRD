"""pytest configuration for the Dam Safety API compliance suite."""

import pytest

from test_helpers import ApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401  (re-exported as fixtures)
    base,
    high,
    low,
    program,
    significant,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client bound to the server under test."""
    return api_client
