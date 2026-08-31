"""Pytest fixtures exposing the athletics test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_alt_headers():
    return TEST_USERS["reviewer_alt_headers"]


@pytest.fixture
def medical_headers():
    return TEST_USERS["medical_headers"]


@pytest.fixture
def medical_alt_headers():
    return TEST_USERS["medical_alt_headers"]


@pytest.fixture
def medical_third_headers():
    return TEST_USERS["medical_third_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def official_headers():
    return TEST_USERS["official_headers"]
