"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; this module is a thin
bridge only (API client + pre-built role headers).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def shop_planner_headers():
    return TEST_USERS["shop_planner_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def operator_headers():
    """Shared Operator headers — only for tests that do NOT exercise
    ownership (role-rejection probes). Ownership-gated calls must build
    per-instance headers with make_operator_headers(operator["id"])."""
    return TEST_USERS["operator_headers"]
