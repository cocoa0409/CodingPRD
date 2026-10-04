"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def accreditation_officer_headers():
    return TEST_USERS["accreditation_officer_headers"]


@pytest.fixture
def plan_coordinator_headers():
    return TEST_USERS["plan_coordinator_headers"]


@pytest.fixture
def surveyor_headers():
    return TEST_USERS["surveyor_headers"]


@pytest.fixture
def public_viewer_headers():
    return TEST_USERS["public_viewer_headers"]
