"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; these fixtures only bridge
the shared API client and the pre-built role headers into tests.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def grm_headers():
    return TEST_USERS["grower_relations_manager_headers"]


@pytest.fixture
def storage_headers():
    return TEST_USERS["storage_operator_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_lead_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def account_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_coordinator_headers"]
