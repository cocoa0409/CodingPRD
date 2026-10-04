"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def national_admin_headers():
    return TEST_USERS["national_admin_headers"]


@pytest.fixture
def tc_admin_headers():
    return TEST_USERS["tc_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def faculty_headers():
    return TEST_USERS["faculty_headers"]


@pytest.fixture
def qa_auditor_headers():
    return TEST_USERS["qa_auditor_headers"]


@pytest.fixture
def employer_headers():
    return TEST_USERS["employer_headers"]
