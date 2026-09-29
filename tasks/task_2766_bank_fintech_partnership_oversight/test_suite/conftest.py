"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_officer_headers():
    return TEST_USERS["program_officer_headers"]


@pytest.fixture
def program_officer_2_headers():
    return TEST_USERS["program_officer_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def risk_committee_headers():
    return TEST_USERS["risk_committee_headers"]


@pytest.fixture
def risk_committee_2_headers():
    return TEST_USERS["risk_committee_2_headers"]


@pytest.fixture
def internal_audit_headers():
    return TEST_USERS["internal_audit_headers"]


@pytest.fixture
def fintech_partner_headers():
    """Unbound fallback only. Partner-scoped calls must build headers per partner."""
    return TEST_USERS["fintech_partner_headers"]
