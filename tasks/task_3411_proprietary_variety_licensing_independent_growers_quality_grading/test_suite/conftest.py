"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def breeding_manager_headers():
    return TEST_USERS["breeding_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def nursery_manager_headers():
    return TEST_USERS["nursery_manager_headers"]


@pytest.fixture
def grower_principal_headers():
    return TEST_USERS["grower_principal_headers"]


@pytest.fixture
def cooling_operator_headers():
    return TEST_USERS["cooling_operator_headers"]


@pytest.fixture
def quality_grader_headers():
    return TEST_USERS["quality_grader_headers"]


@pytest.fixture
def settlement_officer_headers():
    return TEST_USERS["settlement_officer_headers"]
