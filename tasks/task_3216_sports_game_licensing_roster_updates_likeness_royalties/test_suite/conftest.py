"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def licensing_admin_headers():
    return TEST_USERS["licensing_admin_headers"]


@pytest.fixture
def rights_officer_headers():
    return TEST_USERS["rights_officer_headers"]


@pytest.fixture
def roster_operator_headers():
    return TEST_USERS["roster_operator_headers"]


@pytest.fixture
def roster_reviewer_headers():
    return TEST_USERS["roster_reviewer_headers"]


@pytest.fixture
def liveops_manager_headers():
    return TEST_USERS["liveops_manager_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def league_auditor_headers():
    return TEST_USERS["league_auditor_headers"]


@pytest.fixture
def union_auditor_headers():
    return TEST_USERS["union_auditor_headers"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]
