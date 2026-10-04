"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def study_admin_headers():
    return TEST_USERS["study_admin_headers"]


@pytest.fixture
def methodology_lead_headers():
    return TEST_USERS["methodology_lead_headers"]


@pytest.fixture
def field_ops_headers():
    return TEST_USERS["field_ops_headers"]


@pytest.fixture
def awards_officer_headers():
    return TEST_USERS["awards_officer_headers"]


@pytest.fixture
def licensing_manager_headers():
    return TEST_USERS["licensing_manager_headers"]


@pytest.fixture
def press_user_headers():
    return TEST_USERS["press_user_headers"]


@pytest.fixture
def client_user_headers():
    return TEST_USERS["client_user_headers"]
