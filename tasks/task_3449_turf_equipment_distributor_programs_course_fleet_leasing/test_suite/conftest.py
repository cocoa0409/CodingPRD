"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; the API client is session-scoped.
Role-header fixtures expose the shared constants from TEST_USERS — tests that
exercise ownership use the make_*_headers builders with the backing entity's
id instead.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def corporate_admin_headers():
    return TEST_USERS["corporate_admin_headers"]


@pytest.fixture
def distributor_manager_headers():
    return TEST_USERS["distributor_manager_headers"]


@pytest.fixture
def course_manager_headers():
    return TEST_USERS["course_manager_headers"]


@pytest.fixture
def irrigation_dealer_headers():
    return TEST_USERS["irrigation_dealer_headers"]
