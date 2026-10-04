"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def regulatory_headers():
    return TEST_USERS["regulatory_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def quality_headers():
    return TEST_USERS["quality_headers"]


@pytest.fixture
def conversion_mgr_headers():
    return TEST_USERS["conversion_mgr_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def facility_director_headers():
    return TEST_USERS["facility_director_headers"]


@pytest.fixture
def gpo_analyst_headers():
    return TEST_USERS["gpo_analyst_headers"]
