"""Pytest fixtures exposing the HMDA test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    no_auth_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def institution_admin_headers():
    return TEST_USERS["institution_admin_headers"]


@pytest.fixture
def loan_officer_headers():
    return TEST_USERS["loan_officer_headers"]


@pytest.fixture
def compliance_analyst_headers():
    return TEST_USERS["compliance_analyst_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def anonymous_headers():
    return no_auth_headers()
