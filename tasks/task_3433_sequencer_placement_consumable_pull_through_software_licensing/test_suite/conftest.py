"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; `test_helpers` is importable
directly. These fixtures are thin bridges so tests can request the shared API
client and per-role header dicts by name.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def account_manager_headers() -> dict:
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def finance_admin_headers() -> dict:
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def field_service_engineer_headers() -> dict:
    return TEST_USERS["field_service_engineer_headers"]


@pytest.fixture
def supply_planner_headers() -> dict:
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def lab_operator_headers() -> dict:
    """Fallback shared LabOperator headers. Ownership-gated calls must use
    test_helpers.make_lab_operator_headers(account_id) instead."""
    return TEST_USERS["lab_operator_headers"]
