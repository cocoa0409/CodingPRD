"""Shared pytest fixtures for the worksite indemnity compliance suite."""

import pytest

from test_helpers.api_client import ApiClient


@pytest.fixture
def client():
    """A client bound to the service under test.

    The harness restarts the service before each test, so every test opens against an
    empty store with the logical clock at its 2026-09-01T00:00:00Z start value.
    """
    return ApiClient()
