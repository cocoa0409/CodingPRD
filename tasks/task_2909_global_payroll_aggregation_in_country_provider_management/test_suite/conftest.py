"""Pytest bridge between the shared test infrastructure and the test modules.

The harness restarts the API server before every individual test, so no fixture
here holds state across tests: the `api` fixture only hands out the shared client
instance, and every test rebuilds its own preconditions through the API.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    CONTROLLER_2_HEADERS,
    CONTROLLER_HEADERS,
    OPS_2_HEADERS,
    OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    TREASURY_APPROVER_HEADERS,
    TREASURY_RELEASER_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client for the `/payroll` surface."""
    return api_client


@pytest.fixture(scope="session")
def test_users():
    """Every pre-built role header dictionary, keyed by role nickname."""
    return TEST_USERS


@pytest.fixture(scope="session")
def platform_admin_headers():
    """`PlatformAdmin` registers the reference data of the payroll estate."""
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture(scope="session")
def ops_headers():
    """`GlobalPayrollOps` runs the payroll calendar."""
    return OPS_HEADERS


@pytest.fixture(scope="session")
def ops_2_headers():
    """A second `GlobalPayrollOps` principal, for segregation-of-duties setups."""
    return OPS_2_HEADERS


@pytest.fixture(scope="session")
def controller_headers():
    """`PayrollController` owns review and governance."""
    return CONTROLLER_HEADERS


@pytest.fixture(scope="session")
def controller_2_headers():
    """A second `PayrollController` principal, distinct from the first."""
    return CONTROLLER_2_HEADERS


@pytest.fixture(scope="session")
def treasury_approver_headers():
    """The `TreasuryOfficer` that takes the first of the two authorizations."""
    return TREASURY_APPROVER_HEADERS


@pytest.fixture(scope="session")
def treasury_releaser_headers():
    """The second, distinct `TreasuryOfficer` that releases the money."""
    return TREASURY_RELEASER_HEADERS


@pytest.fixture(scope="session")
def auditor_headers():
    """`ComplianceAuditor` owns payroll data privacy."""
    return AUDITOR_HEADERS
