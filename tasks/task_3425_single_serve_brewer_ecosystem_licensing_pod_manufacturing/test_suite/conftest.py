"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every test, so every test starts
against an empty database and must build its own preconditions.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def licensing_headers():
    return TEST_USERS["licensing_manager_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["quality_auditor_headers"]


@pytest.fixture
def brand_manager_headers():
    """Fallback BrandManager identity — safe only for non-ownership calls.
    Ownership-gated calls must use make_brand_manager_headers(brand_id)."""
    return TEST_USERS["brand_manager_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["operations_director_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def category_headers():
    return TEST_USERS["category_manager_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_analyst_headers"]


@pytest.fixture
def support_headers():
    return TEST_USERS["support_agent_headers"]
