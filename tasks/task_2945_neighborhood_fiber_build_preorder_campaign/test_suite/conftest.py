"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def permit_office_headers():
    return TEST_USERS["permit_office_headers"]


@pytest.fixture
def utility_operator_headers():
    return TEST_USERS["utility_operator_headers"]


@pytest.fixture
def install_coordinator_headers():
    return TEST_USERS["install_coordinator_headers"]


@pytest.fixture
def claims_assessor_headers():
    return TEST_USERS["claims_assessor_headers"]


@pytest.fixture
def claims_approver_headers():
    return TEST_USERS["claims_approver_headers"]


@pytest.fixture
def claims_assessor_2_headers():
    return TEST_USERS["claims_assessor_2_headers"]


@pytest.fixture
def claims_approver_2_headers():
    return TEST_USERS["claims_approver_2_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def mdu_owner_headers():
    return TEST_USERS["mdu_owner_headers"]
