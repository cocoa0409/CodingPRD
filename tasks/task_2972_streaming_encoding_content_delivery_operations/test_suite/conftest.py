"""Shared pytest fixtures for the Streaming Encoding & Delivery Operations suite.

The runner starts a fresh server before every individual test, so each test
begins against an empty database with the logical clock reading exactly
`2026-08-01T00:00:00Z` (PRD §2.5).  No fixture here mutates global state that a
later test could observe.
"""

import pytest

from test_helpers.api_client import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client bound to the server under test (API_BASE_URL)."""
    return ApiClient()
