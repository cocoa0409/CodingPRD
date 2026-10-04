"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; the suite assumes the API is
reachable at API_BASE_URL and that every test starts against an empty database
(the harness restarts the server before each test).
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def pm_headers() -> dict:
    return TEST_USERS["portfolio_manager_headers"]


@pytest.fixture
def pm_proposer_headers() -> dict:
    return TEST_USERS["portfolio_manager_proposer_headers"]


@pytest.fixture
def pm_proposer_2_headers() -> dict:
    return TEST_USERS["portfolio_manager_proposer_2_headers"]


@pytest.fixture
def pm_decider_headers() -> dict:
    return TEST_USERS["portfolio_manager_decider_headers"]


@pytest.fixture
def pm_decider_2_headers() -> dict:
    return TEST_USERS["portfolio_manager_decider_2_headers"]


@pytest.fixture
def scp_headers() -> dict:
    return TEST_USERS["supply_chain_planner_headers"]


@pytest.fixture
def fc_headers() -> dict:
    return TEST_USERS["finance_controller_headers"]
