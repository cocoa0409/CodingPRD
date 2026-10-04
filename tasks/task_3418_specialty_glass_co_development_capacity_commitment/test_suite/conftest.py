"""Pytest fixtures exposing the shared test infrastructure.

The runner owns the server lifecycle and injects ``API_BASE_URL`` before
pytest starts; the shared ``ApiClient`` already reads that variable, so this
module only re-exposes the client and the pre-built role headers as fixtures.
It deliberately resets nothing else — the harness restarts the server before
every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def capacity_planner_headers():
    return TEST_USERS["capacity_planner_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def device_maker_headers():
    return TEST_USERS["device_maker_headers"]
