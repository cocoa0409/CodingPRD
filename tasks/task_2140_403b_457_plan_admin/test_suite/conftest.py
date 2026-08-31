"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def officer_two_headers():
    return TEST_USERS["compliance_officer_two_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["plan_sponsor_admin_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_representative_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
