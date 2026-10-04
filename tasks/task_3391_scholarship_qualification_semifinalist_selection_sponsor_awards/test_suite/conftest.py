"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; every test starts against a
freshly restarted server (empty database, logical clock 2026-09-01T00:00:00Z).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def school_official_headers():
    return TEST_USERS["school_official_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def sponsor_admin_headers():
    return TEST_USERS["sponsor_admin_headers"]


@pytest.fixture
def college_admin_headers():
    return TEST_USERS["college_admin_headers"]
