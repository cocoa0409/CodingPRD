"""Shared pytest configuration for the NIL Collective Administration API suite.

The harness restarts the server before each test, so every test builds the state
it needs from scratch through the endpoints of PRD s4. The only shared fixture is
the HTTP client itself.
"""

import pytest

from test_helpers.api_client import NilApiClient


@pytest.fixture
def api() -> NilApiClient:
    """A client aimed at the server under test."""
    return NilApiClient()
