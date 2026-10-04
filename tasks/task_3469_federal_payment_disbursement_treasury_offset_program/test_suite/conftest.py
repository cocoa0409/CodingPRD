"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle (start/stop/restart before every test) is owned by the
test runner; these fixtures only bridge the pre-built helpers into pytest.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner guarantees the server is up."""
    return api_client


@pytest.fixture
def treasury_supervisor_headers():
    return TEST_USERS["treasury_supervisor_headers"]


@pytest.fixture
def treasury_operator_headers():
    return TEST_USERS["treasury_operator_headers"]


@pytest.fixture
def payment_agency_analyst_headers():
    return TEST_USERS["payment_agency_analyst_headers"]


@pytest.fixture
def creditor_analyst_headers():
    """Shared CreditorAnalyst constant — only for tests that never touch an
    owned resource; ownership-gated calls need per-creditor headers."""
    return TEST_USERS["creditor_analyst_headers"]


@pytest.fixture
def state_coordinator_headers():
    return TEST_USERS["state_coordinator_headers"]


@pytest.fixture
def refund_officer_headers():
    return TEST_USERS["refund_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
