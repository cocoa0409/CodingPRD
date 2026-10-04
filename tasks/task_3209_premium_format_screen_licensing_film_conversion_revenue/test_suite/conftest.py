"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def network_planner_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def studio_manager_headers():
    return TEST_USERS["studio_manager_headers"]


@pytest.fixture
def post_scheduler_headers():
    return TEST_USERS["post_scheduler_headers"]


@pytest.fixture
def qa_reviewer_headers():
    return TEST_USERS["qa_reviewer_headers"]


@pytest.fixture
def release_scheduler_headers():
    return TEST_USERS["release_scheduler_headers"]


@pytest.fixture
def box_office_analyst_headers():
    return TEST_USERS["box_office_analyst_headers"]


@pytest.fixture
def field_engineer_headers():
    return TEST_USERS["field_engineer_headers"]


@pytest.fixture
def exhibitor_finance_headers():
    return TEST_USERS["exhibitor_finance_headers"]
