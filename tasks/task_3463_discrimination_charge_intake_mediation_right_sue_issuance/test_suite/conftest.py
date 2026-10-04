"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle, PYTHONPATH, and API_BASE_URL injection;
these fixtures only bridge test_helpers objects into the pytest namespace.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def intake_officer_headers():
    return TEST_USERS["intake_officer_headers"]


@pytest.fixture
def charging_party_headers():
    return TEST_USERS["charging_party_headers"]


@pytest.fixture
def respondent_rep_headers():
    return TEST_USERS["respondent_rep_headers"]


@pytest.fixture
def mediator_headers():
    return TEST_USERS["mediator_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def state_agency_officer_headers():
    return TEST_USERS["state_agency_officer_headers"]
