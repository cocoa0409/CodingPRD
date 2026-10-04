"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def lab_manager_headers():
    return TEST_USERS["lab_manager_headers"]


@pytest.fixture
def editorial_director_headers():
    return TEST_USERS["editorial_director_headers"]


@pytest.fixture
def methodology_officer_headers():
    return TEST_USERS["methodology_officer_headers"]


@pytest.fixture
def purchasing_agent_headers():
    return TEST_USERS["purchasing_agent_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def survey_director_headers():
    return TEST_USERS["survey_director_headers"]


@pytest.fixture
def content_editor_headers():
    return TEST_USERS["content_editor_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
