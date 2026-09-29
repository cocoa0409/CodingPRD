"""Shared pytest fixtures for the Retailer Installation Services API suite.

The harness restarts the API server before every individual test, so each test
runs against an empty database and a logical clock reading exactly
``2026-08-01T00:00:00.000Z``. Fixtures therefore only supply the client and the
identity headers; every precondition is built inside the test (or by a helper in
``test_helpers.fixtures``) through the documented endpoints.
"""

import pytest

from test_helpers import (
    ApiClient,
    make_customer_headers,
    make_installer_headers,
    make_network_manager_headers,
    make_program_admin_headers,
    make_project_coordinator_headers,
    make_service_manager_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """One client for the whole session; it holds no per-test state."""
    return ApiClient()


# ---------------------------------------------------------------------------
# Operator roles carry an opaque `X-User-ID` that is never matched against an
# entity id, so one stable handle per role is correct — and each role gets its
# own handle so recorded actor ids identify who acted.
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return make_program_admin_headers()


@pytest.fixture
def network_manager_headers():
    return make_network_manager_headers()


@pytest.fixture
def coordinator_headers():
    return make_project_coordinator_headers()


@pytest.fixture
def service_manager_headers():
    return make_service_manager_headers()


# ---------------------------------------------------------------------------
# `Installer` and `Customer` carry the id of their own row, so their headers can
# only be built once the row exists. These factories keep that explicit.
# ---------------------------------------------------------------------------
@pytest.fixture
def installer_headers_for():
    return make_installer_headers


@pytest.fixture
def customer_headers_for():
    return make_customer_headers
