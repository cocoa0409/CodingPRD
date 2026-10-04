"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def mfg_headers():
    return TEST_USERS["manufacturing_qa_headers"]


@pytest.fixture
def ra_headers():
    return TEST_USERS["regulatory_affairs_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["distribution_planner_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_operator_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["cold_chain_reviewer_headers"]


@pytest.fixture
def msl_headers():
    return TEST_USERS["medical_science_liaison_headers"]