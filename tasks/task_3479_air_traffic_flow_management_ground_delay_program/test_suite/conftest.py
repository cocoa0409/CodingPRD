"""Shared pytest wiring for the Air Traffic Flow Management suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API. The runner injects API_BASE_URL into the environment; the client reads it
at construction, so the client fixture is function-scoped rather than shared.
"""

import pytest

from test_helpers import (
    COMMAND_CENTER_HEADERS,
    FLOW_MANAGER_HEADERS,
    OPERATOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    ApiClient,
)
from test_helpers import fixtures


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def admin_headers():
    """SystemAdministrator headers: facilities, operators and the clock."""
    return SYSTEM_ADMIN_HEADERS


@pytest.fixture()
def flow_manager_headers():
    """FlowManager headers (opaque id fm-1, the recipes' default proposer)."""
    return FLOW_MANAGER_HEADERS


@pytest.fixture()
def command_center_headers():
    """CommandCenterAdmin headers (opaque id cc-1, distinct from fm-1)."""
    return COMMAND_CENTER_HEADERS


@pytest.fixture()
def operator_headers():
    """Fallback Operator headers - safe only where ownership is not exercised.
    Ownership-gated writes build headers from the created operator's id via
    test_helpers.make_operator_headers(operator["id"])."""
    return OPERATOR_HEADERS


@pytest.fixture()
def world(api: ApiClient):
    """The canonical ACTIVE ground delay program: airport KEWR (base 30),
    carriers Alpha Air and Bravo Air, a published PLANNING forecast, and a
    rate-6 GDP over 13:00-15:00 with five flights slotted by ration-by-schedule."""
    return fixtures.setup_active_gdp(api)
