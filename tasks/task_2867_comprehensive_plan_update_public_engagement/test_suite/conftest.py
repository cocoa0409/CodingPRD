"""Shared pytest wiring for the comprehensive plan update compliance suite.

The harness relaunches the service before every individual test, so each test
starts against an empty database with the logical clock at its startup value of
2026-08-01T00:00:00Z, and builds every precondition it needs through the public
API. The base URL comes from the runner's environment, so the client takes no
arguments.
"""

import pytest

from test_helpers.api_client import PlanningApiClient


@pytest.fixture
def api() -> PlanningApiClient:
    """A client pointed at the service under test."""
    return PlanningApiClient()
