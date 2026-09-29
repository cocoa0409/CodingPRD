"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def surplus_assessor_headers():
    return TEST_USERS["surplus_assessor_headers"]


@pytest.fixture
def disposal_officer_headers():
    return TEST_USERS["disposal_officer_headers"]


@pytest.fixture
def clearance_technician_headers():
    return TEST_USERS["clearance_technician_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def agency_officer_headers():
    """Shared AgencyOfficer headers. The PRD resolves this role's X-User-ID
    against an Agency row, so ownership-gated calls must instead use
    make_agency_officer_headers(agency_id)."""
    return TEST_USERS["agency_officer_headers"]


@pytest.fixture
def bidder_headers():
    """Shared Bidder headers. The PRD resolves this role's X-User-ID against a
    Bidder row, so ownership-gated calls must instead use
    make_bidder_headers(bidder_id)."""
    return TEST_USERS["bidder_headers"]
