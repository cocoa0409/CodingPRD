"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def career_center_admin_headers():
    return TEST_USERS["career_center_admin_headers"]


@pytest.fixture
def employer_recruiter_headers():
    return TEST_USERS["employer_recruiter_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]
