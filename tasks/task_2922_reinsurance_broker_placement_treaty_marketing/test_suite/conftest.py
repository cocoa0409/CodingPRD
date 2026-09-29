"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin — seeds the counterparty registry and drives the clock."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def placement_lead_headers():
    """BrokerPlacementLead — structures, markets, firm-orders, signs down and binds."""
    return TEST_USERS["placement_lead_headers"]


@pytest.fixture
def placement_lead_2_headers():
    """A second BrokerPlacementLead identity (lead-2)."""
    return TEST_USERS["placement_lead_2_headers"]


@pytest.fixture
def actuary_headers():
    """BrokerActuary — signs off exposure packages and generates renewal analytics."""
    return TEST_USERS["actuary_headers"]


@pytest.fixture
def accountant_headers():
    """BrokerAccountant — books, settles and closes the placement year (acct-1)."""
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def accountant_2_headers():
    """A second BrokerAccountant identity (acct-2)."""
    return TEST_USERS["accountant_2_headers"]


@pytest.fixture
def compliance_headers():
    """ComplianceOfficer — suspension, security posture, checkpoint and reversal."""
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def unknown_cedent_underwriter_headers():
    """A CedentUnderwriter identity that resolves to no cedent at all."""
    return TEST_USERS["unknown_cedent_underwriter_headers"]


@pytest.fixture
def unknown_reinsurer_underwriter_headers():
    """A ReinsurerUnderwriter identity that resolves to no reinsurer at all."""
    return TEST_USERS["unknown_reinsurer_underwriter_headers"]
