"""Pytest fixtures exposing the shared test infrastructure.

Server lifecycle, API_BASE_URL injection and PYTHONPATH are owned by the
runner; these fixtures only hand the client and role headers to tests.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def em_headers():
    return TEST_USERS["engagement_manager_headers"]


@pytest.fixture
def co_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def cc_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def comp_headers():
    return TEST_USERS["compensation_committee_headers"]


@pytest.fixture
def anon_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]