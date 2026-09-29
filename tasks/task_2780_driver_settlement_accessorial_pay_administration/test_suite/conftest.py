"""Pytest fixtures exposing the test_helpers infrastructure to the suite."""

import pytest

from test_helpers import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    APPROVER_ALT_HEADERS,
    APPROVER_HEADERS,
    AUDITOR_HEADERS,
    CLERK_ALT_HEADERS,
    CLERK_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """Primary PayrollAdmin identity."""
    return ADMIN_HEADERS


@pytest.fixture
def admin_alt_headers():
    """Second PayrollAdmin identity, for segregation-of-duties chains."""
    return ADMIN_ALT_HEADERS


@pytest.fixture
def clerk_headers():
    """Primary SettlementClerk identity."""
    return CLERK_HEADERS


@pytest.fixture
def clerk_alt_headers():
    """Second SettlementClerk identity."""
    return CLERK_ALT_HEADERS


@pytest.fixture
def approver_headers():
    """Primary SettlementApprover identity."""
    return APPROVER_HEADERS


@pytest.fixture
def approver_alt_headers():
    """Second SettlementApprover identity."""
    return APPROVER_ALT_HEADERS


@pytest.fixture
def auditor_headers():
    """Read-only ComplianceAuditor identity."""
    return AUDITOR_HEADERS
