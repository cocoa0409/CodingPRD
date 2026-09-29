"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_guardian_headers,
    make_provider_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin"]


@pytest.fixture
def eligibility_officer_headers():
    return TEST_USERS["eligibility_officer"]


@pytest.fixture
def expense_reviewer_headers():
    return TEST_USERS["expense_reviewer"]


@pytest.fixture
def second_expense_reviewer_headers():
    return TEST_USERS["second_expense_reviewer"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer"]


@pytest.fixture
def vendor_screener_headers():
    return TEST_USERS["vendor_screener"]


@pytest.fixture
def guardian_headers_for():
    """Builder for ownership-gated calls made as the guardian of one student."""
    return make_guardian_headers


@pytest.fixture
def provider_headers_for():
    """Builder for ownership-gated calls made as one provider acting as itself."""
    return make_provider_headers
