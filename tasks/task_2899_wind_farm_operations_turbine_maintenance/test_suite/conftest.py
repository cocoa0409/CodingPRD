"""Pytest fixtures exposing the wind-ops test infrastructure.

The harness restarts the API server before every test, so the client is
function-scoped and every test builds the state it needs from scratch.
"""

import pytest

from test_helpers import WindOpsApiClient
from test_helpers.test_users import (
    make_commercial_headers,
    make_control_room_headers,
    make_engineer_headers,
    make_planner_headers,
    make_site_admin_headers,
)


@pytest.fixture
def api() -> WindOpsApiClient:
    """HTTP client for the wind-ops API under test."""
    return WindOpsApiClient()


@pytest.fixture
def admin_headers():
    """SiteAdmin credentials."""
    return make_site_admin_headers()


@pytest.fixture
def operator_headers():
    """ControlRoomOperator credentials."""
    return make_control_room_headers()


@pytest.fixture
def planner_headers():
    """MaintenancePlanner credentials."""
    return make_planner_headers()


@pytest.fixture
def engineer_headers():
    """ReliabilityEngineer credentials."""
    return make_engineer_headers()


@pytest.fixture
def commercial_headers():
    """CommercialManager credentials."""
    return make_commercial_headers()
