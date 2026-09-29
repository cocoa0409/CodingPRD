"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def qc_analyst_headers():
    return TEST_USERS["qc_analyst_headers"]


@pytest.fixture
def qc_analyst_2_headers():
    return TEST_USERS["qc_analyst_2_headers"]


@pytest.fixture
def production_operator_headers():
    return TEST_USERS["production_operator_headers"]


@pytest.fixture
def qa_releaser_headers():
    return TEST_USERS["qa_releaser_headers"]


@pytest.fixture
def qa_releaser_2_headers():
    return TEST_USERS["qa_releaser_2_headers"]


@pytest.fixture
def qa_releaser_3_headers():
    return TEST_USERS["qa_releaser_3_headers"]


@pytest.fixture
def regulatory_affairs_headers():
    return TEST_USERS["regulatory_affairs_headers"]


@pytest.fixture
def regulatory_affairs_2_headers():
    return TEST_USERS["regulatory_affairs_2_headers"]


@pytest.fixture
def distribution_planner_headers():
    return TEST_USERS["distribution_planner_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
