"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def regulatory_reviewer_headers():
    return TEST_USERS["regulatory_reviewer_headers"]


@pytest.fixture
def facility_inspector_headers():
    return TEST_USERS["facility_inspector_headers"]
