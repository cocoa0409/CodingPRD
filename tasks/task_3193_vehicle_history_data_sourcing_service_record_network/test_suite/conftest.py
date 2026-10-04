"""Pytest wiring for the Vehicle History Network test suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public API.
"""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_dealer_agent_headers,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_shop_operator_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return api_client


@pytest.fixture()
def admin_headers():
    return make_network_admin_headers()


@pytest.fixture()
def guarantee_admin_headers():
    return make_guarantee_admin_headers()
