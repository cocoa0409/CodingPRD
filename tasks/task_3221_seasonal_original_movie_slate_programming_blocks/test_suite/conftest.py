"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def slate_planner_headers():
    return TEST_USERS["slate_planner_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def talent_agent_headers():
    return TEST_USERS["talent_agent_headers"]


@pytest.fixture
def programming_exec_headers():
    return TEST_USERS["programming_exec_headers"]


@pytest.fixture
def ad_sales_rep_headers():
    return TEST_USERS["ad_sales_rep_headers"]


@pytest.fixture
def streaming_curator_headers():
    return TEST_USERS["streaming_curator_headers"]


@pytest.fixture
def licensing_manager_headers():
    return TEST_USERS["licensing_manager_headers"]
