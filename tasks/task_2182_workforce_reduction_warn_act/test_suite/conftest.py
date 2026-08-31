"""Pytest fixtures exposing the generated test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def lead_headers():
    return TEST_USERS["lead_headers"]


@pytest.fixture
def lead_2_headers():
    return TEST_USERS["lead_2_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]


@pytest.fixture
def counsel_2_headers():
    return TEST_USERS["counsel_2_headers"]


@pytest.fixture
def benefits_headers():
    return TEST_USERS["benefits_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
