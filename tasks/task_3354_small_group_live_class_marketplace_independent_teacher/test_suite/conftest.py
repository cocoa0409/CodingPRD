"""Pytest fixtures exposing the test_helpers infrastructure.

Server lifecycle (start/stop/restart before every test) is owned by
prd-bench-local-runner; these fixtures only hand tests a client and the
role headers for the PRD's five roles.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server before each test."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def teacher_reviewer_headers():
    return TEST_USERS["teacher_reviewer_headers"]


@pytest.fixture
def teacher_applicant_headers():
    return TEST_USERS["teacher_applicant_headers"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
