"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_alt_headers():
    return TEST_USERS["admin_alt_headers"]


@pytest.fixture
def board_headers():
    return TEST_USERS["board_headers"]


@pytest.fixture
def board_alt_headers():
    return TEST_USERS["board_alt_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_alt_headers():
    return TEST_USERS["officer_alt_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def compliance_alt_headers():
    return TEST_USERS["compliance_alt_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
