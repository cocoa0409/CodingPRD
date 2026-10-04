"""Pytest fixtures exposing the test_helpers infrastructure.

Server lifecycle is managed by the runner; these fixtures only bridge the
helpers into pytest's fixture namespace.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is restarted per test by the runner."""
    return api_client


@pytest.fixture
def agency_officer_headers():
    return TEST_USERS["agency_officer_headers"]


@pytest.fixture
def principal_investigator_headers():
    return TEST_USERS["principal_investigator_headers"]


@pytest.fixture
def study_director_headers():
    return TEST_USERS["study_director_headers"]


@pytest.fixture
def data_manager_headers():
    return TEST_USERS["data_manager_headers"]


@pytest.fixture
def irb_reviewer_headers():
    return TEST_USERS["irb_reviewer_headers"]


@pytest.fixture
def peer_reviewer_headers():
    return TEST_USERS["peer_reviewer_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def external_researcher_headers():
    return TEST_USERS["external_researcher_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
