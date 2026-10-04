"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def division_president_headers():
    return TEST_USERS["division_president_headers"]


@pytest.fixture
def land_manager_headers():
    return TEST_USERS["land_manager_headers"]


@pytest.fixture
def community_manager_headers():
    return TEST_USERS["community_manager_headers"]


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]


@pytest.fixture
def trade_partner_headers():
    return TEST_USERS["trade_partner_headers"]
