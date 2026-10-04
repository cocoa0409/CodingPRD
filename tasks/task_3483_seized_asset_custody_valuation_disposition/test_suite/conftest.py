"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, create_api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return create_api_client()


@pytest.fixture
def case_agent_headers():
    return TEST_USERS["case_agent_headers"]


@pytest.fixture
def court_official_headers():
    return TEST_USERS["court_official_headers"]


@pytest.fixture
def second_court_official_headers():
    return TEST_USERS["second_court_official_headers"]


@pytest.fixture
def asset_custodian_headers():
    return TEST_USERS["asset_custodian_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]


@pytest.fixture
def auction_coordinator_headers():
    return TEST_USERS["auction_coordinator_headers"]


@pytest.fixture
def fund_administrator_headers():
    return TEST_USERS["fund_administrator_headers"]


@pytest.fixture
def second_fund_administrator_headers():
    return TEST_USERS["second_fund_administrator_headers"]


@pytest.fixture
def claimant_headers():
    """Shared Claimant headers. The PRD pins a Claimant's X-User-ID to the
    interest's petitioner_ref on file/appeal, so those calls must instead use
    make_claimant_headers(petitioner_ref)."""
    return TEST_USERS["claimant_headers"]


@pytest.fixture
def second_claimant_headers():
    return TEST_USERS["second_claimant_headers"]


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]
