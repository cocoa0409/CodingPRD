"""Shared pytest fixtures for the recruitment service's compliance suite."""

import pytest

from test_helpers.api_client import MepApiClient


@pytest.fixture
def client():
    """A client bound to the service under test.

    The harness restarts the service before each test, so every test opens against an
    empty store with the logical clock at its 2026-08-01T00:00:00Z start value.
    """
    return MepApiClient()
