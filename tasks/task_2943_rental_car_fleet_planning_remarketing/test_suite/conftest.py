"""Shared pytest fixtures for the fleet planning and remarketing suite.

The runner owns the server: it starts one, exports ``API_BASE_URL`` and
relaunches it before every individual test, so each test below begins against
an empty database and never has to health-check anything itself.
"""

import pytest

from test_helpers import (
    ApiClient,
    fixtures,
    make_fleet_controller_headers,
    make_fleet_planner_headers,
    make_platform_admin_headers,
    make_remarketing_manager_headers,
)


@pytest.fixture
def client() -> ApiClient:
    """A client bound to the base URL the runner exported."""
    return ApiClient()


@pytest.fixture
def admin(client):
    """Headers for the role that owns the reference configuration."""
    return make_platform_admin_headers()


@pytest.fixture
def planner(client):
    return make_fleet_planner_headers()


@pytest.fixture
def controller(client):
    return make_fleet_controller_headers()


@pytest.fixture
def manager(client):
    return make_remarketing_manager_headers()


@pytest.fixture
def world(client):
    """Markets, a segment, both program kinds, channels and one live policy."""
    return fixtures.setup_reference_world(client)
