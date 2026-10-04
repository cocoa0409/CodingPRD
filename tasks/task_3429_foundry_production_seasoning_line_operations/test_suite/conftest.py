"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle and PYTHONPATH; tests import domain
helpers from test_helpers and use the `api` fixture for raw endpoint calls.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def foundry_manager_headers():
    return TEST_USERS["foundry_manager_headers"]


@pytest.fixture
def melt_operator_headers():
    return TEST_USERS["melt_operator_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def seasoning_lead_headers():
    return TEST_USERS["seasoning_lead_headers"]


@pytest.fixture
def environmental_officer_headers():
    return TEST_USERS["environmental_officer_headers"]


@pytest.fixture
def environmental_officer_2_headers():
    return TEST_USERS["environmental_officer_2_headers"]


@pytest.fixture
def retail_planner_headers():
    return TEST_USERS["retail_planner_headers"]


@pytest.fixture
def outlet_manager_headers():
    return TEST_USERS["outlet_manager_headers"]
