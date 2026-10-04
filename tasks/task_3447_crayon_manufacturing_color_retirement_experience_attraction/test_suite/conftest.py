"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sourcing_headers():
    return TEST_USERS["sourcing_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_headers"]


@pytest.fixture
def qa2_headers():
    return TEST_USERS["qa2_headers"]


@pytest.fixture
def formulator_headers():
    return TEST_USERS["formulator_headers"]


@pytest.fixture
def safety_headers():
    return TEST_USERS["safety_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]


@pytest.fixture
def brand_headers():
    return TEST_USERS["brand_headers"]


@pytest.fixture
def brand2_headers():
    return TEST_USERS["brand2_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def boxoffice_headers():
    return TEST_USERS["boxoffice_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]
