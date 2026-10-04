"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests import everything
from test_helpers and assume the server is reachable at API_BASE_URL.
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
def survey_methodologist_headers():
    return TEST_USERS["survey_methodologist_headers"]


@pytest.fixture
def collection_officer_headers():
    return TEST_USERS["collection_officer_headers"]


@pytest.fixture
def estimation_analyst_headers():
    return TEST_USERS["estimation_analyst_headers"]


@pytest.fixture
def estimation_analyst_2_headers():
    return TEST_USERS["estimation_analyst_2_headers"]


@pytest.fixture
def disclosure_officer_headers():
    return TEST_USERS["disclosure_officer_headers"]


@pytest.fixture
def release_manager_headers():
    return TEST_USERS["release_manager_headers"]


@pytest.fixture
def respondent_headers():
    return TEST_USERS["respondent_headers"]


@pytest.fixture
def accredited_media_headers():
    return TEST_USERS["accredited_media_headers"]
