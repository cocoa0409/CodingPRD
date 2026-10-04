"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle and PYTHONPATH; this file only bridges
the generated helpers into pytest's fixture system.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers import fixtures as fx


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def assortment_planner_headers():
    return TEST_USERS["assortment_planner_headers"]


@pytest.fixture
def boutique_manager_headers():
    return TEST_USERS["boutique_manager_headers"]


@pytest.fixture
def retail_lead_headers():
    return TEST_USERS["retail_lead_headers"]


@pytest.fixture
def retail_cashier_headers():
    return TEST_USERS["retail_cashier_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def server_headers():
    return TEST_USERS["server_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def fx_module():
    """The composite-setup helper module, for tests that want it by name."""
    return fx