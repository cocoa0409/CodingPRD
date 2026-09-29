"""Pytest fixtures exposing the parcel-billing test_helpers infrastructure.

The runner relaunches the API server and empties its database before every
individual test, so no fixture here caches domain state — only the HTTP client
and the static role headers are shared.
"""

import pytest

from test_helpers import (
    BILLING_OPS_ALT_HEADERS,
    BILLING_OPS_HEADERS,
    CARRIER_ADMIN_ALT_HEADERS,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_ALT_HEADERS,
    CARRIER_OPS_HEADERS,
    REVENUE_AUDITOR_ALT_HEADERS,
    REVENUE_AUDITOR_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def carrier_admin_headers():
    """Headers for the CarrierAdmin role, which owns the reference data."""
    return CARRIER_ADMIN_HEADERS


@pytest.fixture
def carrier_admin_alt_headers():
    """A second CarrierAdmin identity."""
    return CARRIER_ADMIN_ALT_HEADERS


@pytest.fixture
def carrier_ops_headers():
    """Headers for the CarrierOps role, which inducts and scans parcels."""
    return CARRIER_OPS_HEADERS


@pytest.fixture
def carrier_ops_alt_headers():
    """A second CarrierOps identity."""
    return CARRIER_OPS_ALT_HEADERS


@pytest.fixture
def billing_ops_headers():
    """Headers for the BillingOps role, which sweeps and adjusts invoices."""
    return BILLING_OPS_HEADERS


@pytest.fixture
def billing_ops_alt_headers():
    """A second BillingOps identity, needed to release an adjustment."""
    return BILLING_OPS_ALT_HEADERS


@pytest.fixture
def revenue_auditor_headers():
    """Headers for the RevenueAuditor role, which resolves disputes."""
    return REVENUE_AUDITOR_HEADERS


@pytest.fixture
def revenue_auditor_alt_headers():
    """A second RevenueAuditor identity."""
    return REVENUE_AUDITOR_ALT_HEADERS
