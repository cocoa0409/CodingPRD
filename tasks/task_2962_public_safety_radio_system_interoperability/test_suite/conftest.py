"""Shared pytest fixtures for the Public Safety Radio Interoperability API suite.

The harness relaunches the API server before every individual test, so each
test observes an empty database and a logical clock reading exactly
`2026-08-01T00:00:00Z` (PRD 2.5). Tests that need a different instant move the
clock explicitly.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.constants import CLOCK_STARTUP_DEFAULT  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server the runner started for this test."""
    return ApiClient()


@pytest.fixture
def clock_at_start(api: ApiClient) -> str:
    """Pin the logical clock at its documented startup instant.

    Setting it explicitly makes the instant a stated precondition of the test
    rather than an inherited assumption.
    """
    fx.set_clock(api, CLOCK_STARTUP_DEFAULT)
    return CLOCK_STARTUP_DEFAULT
