"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle and API_BASE_URL injection are owned by the runner; these
fixtures only bridge the helper layer into tests.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def process_engineer_headers() -> dict:
    return TEST_USERS["process_engineer_headers"]


@pytest.fixture
def manufacturing_operator_headers() -> dict:
    return TEST_USERS["manufacturing_operator_headers"]


@pytest.fixture
def manufacturing_operator_2_headers() -> dict:
    return TEST_USERS["manufacturing_operator_2_headers"]


@pytest.fixture
def quality_control_analyst_headers() -> dict:
    return TEST_USERS["quality_control_analyst_headers"]


@pytest.fixture
def quality_control_analyst_2_headers() -> dict:
    return TEST_USERS["quality_control_analyst_2_headers"]


@pytest.fixture
def quality_assurance_reviewer_headers() -> dict:
    return TEST_USERS["quality_assurance_reviewer_headers"]


@pytest.fixture
def quality_assurance_reviewer_2_headers() -> dict:
    return TEST_USERS["quality_assurance_reviewer_2_headers"]


@pytest.fixture
def quality_assurance_reviewer_3_headers() -> dict:
    return TEST_USERS["quality_assurance_reviewer_3_headers"]


@pytest.fixture
def supply_planner_headers() -> dict:
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def regulatory_affairs_specialist_headers() -> dict:
    return TEST_USERS["regulatory_affairs_specialist_headers"]
