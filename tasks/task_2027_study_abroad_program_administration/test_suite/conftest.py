"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_b_headers():
    return TEST_USERS["coordinator_b_headers"]


@pytest.fixture
def faculty_headers():
    return TEST_USERS["faculty_headers"]


@pytest.fixture
def safety_headers():
    return TEST_USERS["safety_headers"]


@pytest.fixture
def bursar_headers():
    return TEST_USERS["bursar_headers"]
