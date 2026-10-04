"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def appeal_reviewer_headers():
    return TEST_USERS["appeal_reviewer_headers"]


@pytest.fixture
def operations_lead_headers():
    return TEST_USERS["operations_lead_headers"]


@pytest.fixture
def liaison_headers():
    return TEST_USERS["liaison_headers"]


@pytest.fixture
def background_reviewer_headers():
    return TEST_USERS["background_reviewer_headers"]


@pytest.fixture
def rider_headers():
    return TEST_USERS["rider_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]