"""Pytest fixtures exposing the shared test infrastructure.

The harness relaunches the server before every test, so the client below is the
only thing that is shared: all domain state is built inside each test's own
fixtures through the public API.
"""

import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["plant_admin"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["plant_admin_2"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["process_engineer"]


@pytest.fixture
def engineer2_headers():
    return TEST_USERS["process_engineer_2"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["kiln_operator"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_technician"]


@pytest.fixture
def lab2_headers():
    return TEST_USERS["lab_technician_2"]


@pytest.fixture
def quality_headers():
    return TEST_USERS["quality_manager"]


@pytest.fixture
def quality2_headers():
    return TEST_USERS["quality_manager_2"]


@pytest.fixture
def env_headers():
    return TEST_USERS["environmental_officer"]


@pytest.fixture
def env2_headers():
    return TEST_USERS["environmental_officer_2"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_planner"]


@pytest.fixture
def logistics2_headers():
    return TEST_USERS["logistics_planner_2"]
