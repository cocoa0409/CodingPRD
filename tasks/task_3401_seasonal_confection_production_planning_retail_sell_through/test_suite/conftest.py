"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; these fixtures only bridge
the shared API client and the pre-built role headers into the test modules.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def category_manager_headers():
    """cm-alice — the default disposition proposer."""
    return TEST_USERS["category_manager_headers"]


@pytest.fixture
def category_manager_b_headers():
    """cm-bob — the default disposition approver (segregation of duties)."""
    return TEST_USERS["category_manager_b_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def retailer_headers():
    """Fallback Retailer headers for tests that never exercise ownership."""
    return TEST_USERS["retailer_headers"]
