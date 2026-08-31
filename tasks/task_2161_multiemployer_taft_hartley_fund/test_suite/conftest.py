"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_employer_headers,
    make_trustee_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def fund_administrator_headers():
    return TEST_USERS["fund_administrator_headers"]


@pytest.fixture
def payroll_auditor_headers():
    return TEST_USERS["payroll_auditor_headers"]


@pytest.fixture
def actuary_headers():
    return TEST_USERS["actuary_headers"]


@pytest.fixture
def employer_headers_for():
    """Factory: ContributingEmployer headers bound to a real Employer id."""
    return make_employer_headers


@pytest.fixture
def trustee_headers_for():
    """Factory: Trustee headers bound to a real Trustee id."""
    return make_trustee_headers
