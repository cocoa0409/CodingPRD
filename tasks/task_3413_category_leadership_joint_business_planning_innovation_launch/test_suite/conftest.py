"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is owned by the local runner (it restarts the API server
before every test and injects API_BASE_URL); this module only wires the
helpers into pytest. No test functions live here.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_retailer_buyer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# One fixture per role from TEST_USERS. The RetailerBuyer shared constant is a
# fallback for non-ownership tests only; ownership-gated calls must use the
# make_retailer_buyer_headers fixture below with the real Retailer.id.

@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def manufacturer_planner_headers() -> dict:
    return TEST_USERS["manufacturer_planner_headers"]


@pytest.fixture
def retailer_buyer_headers() -> dict:
    return TEST_USERS["retailer_buyer_headers"]


@pytest.fixture
def category_advisor_headers() -> dict:
    return TEST_USERS["category_advisor_headers"]


@pytest.fixture
def supply_chain_planner_headers() -> dict:
    return TEST_USERS["supply_chain_planner_headers"]


@pytest.fixture
def finance_analyst_headers() -> dict:
    return TEST_USERS["finance_analyst_headers"]


@pytest.fixture
def buyer_headers_factory():
    """Entity-backed RetailerBuyer identity builder: call with the actual
    Retailer.id whenever the call is ownership-gated (PRD §2.1)."""
    return make_retailer_buyer_headers
