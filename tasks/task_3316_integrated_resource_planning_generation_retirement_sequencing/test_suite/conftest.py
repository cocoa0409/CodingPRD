"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def intervener_headers():
    return TEST_USERS["intervener_headers"]


@pytest.fixture
def commenter_headers():
    return TEST_USERS["commenter_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
