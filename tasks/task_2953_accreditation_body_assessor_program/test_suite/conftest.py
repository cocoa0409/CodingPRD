"""Shared pytest wiring for the accreditation registry suite.

Importing ``test_helpers.api_errors`` has a side effect the whole suite
depends on: it hands the runner's validators the error-id to HTTP-status map
of section 5, so ``validate_error`` can check both halves of every rejection.
"""

import pytest

from test_helpers import api_errors  # noqa: F401  (registers the status map)
from test_helpers.api_client import AccreditationApiClient


@pytest.fixture
def client() -> AccreditationApiClient:
    """A client bound to the base URL the runner exported for this test."""
    return AccreditationApiClient()
