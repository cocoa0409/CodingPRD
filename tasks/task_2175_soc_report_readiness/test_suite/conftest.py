"""Pytest fixtures exposing the SOC test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def compliance_lead_headers():
    return TEST_USERS["compliance_lead_headers"]


@pytest.fixture
def control_owner_headers():
    return TEST_USERS["control_owner_headers"]


@pytest.fixture
def evidence_reviewer_headers():
    return TEST_USERS["evidence_reviewer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def account_executive_headers():
    return TEST_USERS["account_executive_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
