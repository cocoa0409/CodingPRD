"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def underwriter2_headers():
    return TEST_USERS["underwriter2_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def adjuster2_headers():
    return TEST_USERS["adjuster2_headers"]


@pytest.fixture
def adjuster3_headers():
    return TEST_USERS["adjuster3_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]
