"""Shared pytest fixtures for the aviation underwriting compliance suite.

The harness owns the server: it starts a fresh process with an empty store before
each test and injects the base URL through the environment, so no test here ever
starts, stops or health-checks anything.
"""

import pytest

from test_helpers import AviationApiClient


@pytest.fixture
def api() -> AviationApiClient:
    """A client aimed at the API under test."""
    return AviationApiClient()
