"""Shared pytest fixtures.

The runner restarts the server before every test, so every test starts against
an empty database with the logical clock back at its default reading of
2026-08-01T00:00:00Z.
"""
import pytest

from test_helpers import EppApiClient


@pytest.fixture()
def api() -> EppApiClient:
    """A client pointed at the server under test."""
    return EppApiClient()
