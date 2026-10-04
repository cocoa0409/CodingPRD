"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every test, so each test begins
against an empty database and builds the state it needs through the public
API. The base URL comes from the environment, injected by the runner.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def retailer_admin_headers():
    return TEST_USERS["retailer_admin_headers"]


@pytest.fixture
def category_manager_headers():
    return TEST_USERS["category_manager_headers"]


@pytest.fixture
def insights_scientist_headers():
    return TEST_USERS["insights_scientist_headers"]


@pytest.fixture
def data_steward_headers():
    return TEST_USERS["data_steward_headers"]


@pytest.fixture
def supplier_analyst_headers():
    # Fallback only: ownership-gated calls must use
    # make_supplier_analyst_headers(account_id) with the real account id.
    return TEST_USERS["supplier_analyst_headers"]
