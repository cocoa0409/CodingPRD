"""
Shared pytest fixtures for the Hospital Sitter & Continuous Observation Staffing
compliance suite.

The runner owns the server: it starts it, injects ``API_BASE_URL``, restarts it
before every individual test so each test sees an empty database, and collects the
results. Nothing in this suite starts, stops or health-checks a server.
"""

import pytest

from test_helpers import ObservationApiClient


@pytest.fixture
def api() -> ObservationApiClient:
    """A client bound to the base URL the runner injected for this test."""
    return ObservationApiClient()
