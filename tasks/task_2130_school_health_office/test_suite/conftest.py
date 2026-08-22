"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def physician_alt_headers():
    return TEST_USERS["physician_alt_headers"]


@pytest.fixture
def records_officer_headers():
    return TEST_USERS["records_officer_headers"]


@pytest.fixture
def records_officer_alt_headers():
    return TEST_USERS["records_officer_alt_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def aide_headers():
    return TEST_USERS["aide_headers"]


@pytest.fixture
def guardian_headers():
    return TEST_USERS["guardian_headers"]
