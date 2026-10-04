"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def tour_planner_headers():
    return TEST_USERS["tour_planner_headers"]


@pytest.fixture
def talent_relations_headers():
    return TEST_USERS["talent_relations_headers"]


@pytest.fixture
def storyline_editor_headers():
    return TEST_USERS["storyline_editor_headers"]


@pytest.fixture
def distribution_manager_headers():
    return TEST_USERS["distribution_manager_headers"]


@pytest.fixture
def merch_ops_headers():
    return TEST_USERS["merch_ops_headers"]


@pytest.fixture
def medic_headers():
    return TEST_USERS["medic_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]
