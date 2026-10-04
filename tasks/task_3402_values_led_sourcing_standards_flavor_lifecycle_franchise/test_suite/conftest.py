"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the harness, which restarts the API server
before every test; each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def sourcing_manager_headers():
    return TEST_USERS["sourcing_manager_headers"]


@pytest.fixture
def sustainability_auditor_headers():
    return TEST_USERS["sustainability_auditor_headers"]


@pytest.fixture
def audit_verifier_headers():
    return TEST_USERS["audit_verifier_headers"]


@pytest.fixture
def dairy_program_manager_headers():
    return TEST_USERS["dairy_program_manager_headers"]


@pytest.fixture
def flavor_manager_headers():
    return TEST_USERS["flavor_manager_headers"]


@pytest.fixture
def plant_scheduler_headers():
    return TEST_USERS["plant_scheduler_headers"]


@pytest.fixture
def independent_board_member_headers():
    return TEST_USERS["independent_board_member_headers"]


@pytest.fixture
def parent_ops_controller_headers():
    return TEST_USERS["parent_ops_controller_headers"]


@pytest.fixture
def franchise_admin_headers():
    return TEST_USERS["franchise_admin_headers"]


@pytest.fixture
def shop_operator_headers():
    return TEST_USERS["shop_operator_headers"]


@pytest.fixture
def fan_headers():
    return TEST_USERS["fan_headers"]
