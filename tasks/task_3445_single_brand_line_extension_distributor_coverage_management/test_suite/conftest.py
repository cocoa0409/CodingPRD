"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and PYTHONPATH; these fixtures only
bridge the shared API client and the pre-built role headers into tests.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def brand_manager_headers() -> dict:
    return TEST_USERS["brand_manager_headers"]


@pytest.fixture
def trade_secret_officer_headers() -> dict:
    return TEST_USERS["trade_secret_officer_headers"]


@pytest.fixture
def compliance_auditor_headers() -> dict:
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def channel_manager_headers() -> dict:
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def pricing_analyst_headers() -> dict:
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def marketing_manager_headers() -> dict:
    return TEST_USERS["marketing_manager_headers"]


@pytest.fixture
def regulatory_affairs_headers() -> dict:
    return TEST_USERS["regulatory_affairs_headers"]


@pytest.fixture
def supply_planner_headers() -> dict:
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def distributor_contact_headers() -> dict:
    """Shared DistributorContact headers — non-ownership tests only; use
    make_distributor_contact_headers(distributor_id) for gated calls."""
    return TEST_USERS["distributor_contact_headers"]


@pytest.fixture
def consumer_headers() -> dict:
    return TEST_USERS["consumer_headers"]
