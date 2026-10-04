"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def lab_liaison_headers():
    return TEST_USERS["lab_liaison_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def phlebotomist_headers():
    return TEST_USERS["phlebotomist_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]


@pytest.fixture
def lab_system_headers():
    return TEST_USERS["lab_system_headers"]