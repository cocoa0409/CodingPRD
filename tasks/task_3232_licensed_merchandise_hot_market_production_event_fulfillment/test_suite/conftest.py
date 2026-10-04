"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def design_ops_headers():
    return TEST_USERS["design_ops_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def print_operator_headers():
    return TEST_USERS["print_operator_headers"]


@pytest.fixture
def fulfillment_coordinator_headers():
    return TEST_USERS["fulfillment_coordinator_headers"]


@pytest.fixture
def enforcement_agent_headers():
    return TEST_USERS["enforcement_agent_headers"]


@pytest.fixture
def audit_only_headers():
    return TEST_USERS["audit_only_headers"]


@pytest.fixture
def licensing_ops_headers():
    return TEST_USERS["licensing_ops_headers"]