"""Shared pytest wiring for the Retail FX & Travel Money compliance suite.

The runner owns the server lifecycle and hands every test an empty database, so
there is no seeding back door here: each test builds the world it needs through
the public endpoints.  This module only publishes the client and the role headers.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """One client for the whole session; it holds no per-test state."""
    return ApiClient()


@pytest.fixture
def admin_headers() -> dict:
    """PlatformAdmin: branches, currency profiles, routes and the logical clock."""
    return dict(TEST_USERS["admin_headers"])


@pytest.fixture
def treasury_headers() -> dict:
    """TreasuryOfficer: wholesale quotes, rate cards, plan review, logistics."""
    return dict(TEST_USERS["treasury_headers"])


@pytest.fixture
def manager_headers() -> dict:
    """BranchManager: positions, plans, assessments, reversals, arrivals."""
    return dict(TEST_USERS["manager_headers"])


@pytest.fixture
def teller_headers() -> dict:
    """BranchTeller: the counter - customers, deals, detentions, redemptions."""
    return dict(TEST_USERS["teller_headers"])


@pytest.fixture
def teller2_headers() -> dict:
    """A second BranchTeller, for the dual-control and segregation rules."""
    return dict(TEST_USERS["teller2_headers"])


@pytest.fixture
def compliance_headers() -> dict:
    """ComplianceOfficer: decisions, reports and customer compliance holds."""
    return dict(TEST_USERS["compliance_headers"])


@pytest.fixture
def customer_headers() -> dict:
    """A Customer whose X-User-ID is not any live customer row."""
    return dict(TEST_USERS["customer_headers"])
