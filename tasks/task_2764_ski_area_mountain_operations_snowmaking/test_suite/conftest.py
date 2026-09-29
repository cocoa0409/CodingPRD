"""Shared pytest wiring for the mountain operations test suite.

The runner owns the server lifecycle and restarts the service before every
individual test, so each test opens on an empty database and builds the state
its rule needs from scratch.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.fixtures import (  # noqa: E402,F401
    MountainScenario,
    initial_clock,
    inventory,
    mountain,
    open_mountain,
    open_mountain_with_plant,
    ready_area,
    season,
    season_with_lift,
)


@pytest.fixture
def api() -> ApiClient:
    """HTTP client aimed at the service under test."""
    return ApiClient()
