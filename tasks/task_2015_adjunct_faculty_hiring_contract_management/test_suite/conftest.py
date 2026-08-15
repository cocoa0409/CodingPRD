"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def hr_admin_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def hr_reviewer_1_headers():
    return TEST_USERS["hr_reviewer_1_headers"]


@pytest.fixture
def hr_reviewer_2_headers():
    return TEST_USERS["hr_reviewer_2_headers"]


@pytest.fixture
def chair_headers():
    return TEST_USERS["chair_headers"]


@pytest.fixture
def dean_headers():
    return TEST_USERS["dean_headers"]


@pytest.fixture
def payroll_headers():
    return TEST_USERS["payroll_headers"]
