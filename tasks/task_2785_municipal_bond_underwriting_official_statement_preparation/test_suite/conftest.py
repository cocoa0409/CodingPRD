"""Shared fixtures for the municipal bond underwriting suite.

The server lifecycle belongs to the runner: it is relaunched before each test, so
every test starts against an empty database and every fixture below builds its
preconditions from scratch. Composite fixtures delegate to
``test_helpers.fixtures`` so the workflow is described in exactly one place.
"""

import pytest

from test_helpers import ApiClient, api_client
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BOND_COUNSEL_DRAFTER_HEADERS,
    BOND_COUNSEL_REVIEWER_HEADERS,
    COMPLIANCE_HEADERS,
    RATING_ANALYST_HEADERS,
    RATING_ANALYST_OTHER_HEADERS,
)


@pytest.fixture(scope="session")
def client() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque-role headers (PRD section 2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def compliance():
    """Headers for a `ComplianceOfficer`, whose identifier is never persisted."""
    return COMPLIANCE_HEADERS


@pytest.fixture
def counsel():
    """Headers for the drafting `BondCounsel`, recorded as `authored_by_user_id`."""
    return BOND_COUNSEL_DRAFTER_HEADERS


@pytest.fixture
def reviewer():
    """Headers for a second `BondCounsel`, so Rule G-17 approval is possible."""
    return BOND_COUNSEL_REVIEWER_HEADERS


@pytest.fixture
def analyst():
    """Headers for the `RatingAnalyst` who pins engagements to itself."""
    return RATING_ANALYST_HEADERS


@pytest.fixture
def other_analyst():
    """Headers for a second `RatingAnalyst`, unpinned to any engagement."""
    return RATING_ANALYST_OTHER_HEADERS


# ---------------------------------------------------------------------------
# Participant and deal milestones
# ---------------------------------------------------------------------------
@pytest.fixture
def participants(client):
    """An issuer, an advisory firm and an underwriting firm, with their headers."""
    return fx.participants(client)


@pytest.fixture
def draft_deal(client):
    """A DRAFT deal carrying the canonical two-tranche schedule."""
    return fx.draft_deal(client)


@pytest.fixture
def structuring_deal(client):
    """A deal whose maturity schedule has been frozen: STRUCTURING."""
    return fx.structuring_deal(client)


@pytest.fixture
def negotiated_deal(client):
    """A negotiated deal on its pricing branch: PRICING_NEGOTIATED."""
    return fx.negotiated_pricing_deal(client)


@pytest.fixture
def competitive_deal(client):
    """A competitive deal on its pricing branch: PRICING_COMPETITIVE."""
    return fx.competitive_pricing_deal(client)


@pytest.fixture
def priced_negotiated_deal(client):
    """A negotiated deal in PRICED, carrying the PRD's worked money figures."""
    return fx.priced_negotiated_deal(client)


@pytest.fixture
def priced_competitive_deal(client):
    """A competitive deal in PRICED, carrying the PRD's worked bid figures."""
    return fx.priced_competitive_deal(client)


@pytest.fixture
def awarded_negotiated_deal(client):
    """A negotiated deal in AWARDED, so its six closing documents exist."""
    return fx.awarded_negotiated_deal(client)


@pytest.fixture
def awarded_competitive_deal(client):
    """A competitive deal in AWARDED, so its six closing documents exist."""
    return fx.awarded_competitive_deal(client)


@pytest.fixture
def closed_deal(client):
    """A negotiated deal driven to the terminal CLOSED state."""
    return fx.closed_negotiated_deal(client)


@pytest.fixture
def refunding_context(client):
    """A CLOSED prior issue plus a fresh DRAFT deal for the same issuer."""
    return fx.refunding_context(client)


# ---------------------------------------------------------------------------
# The order book
# ---------------------------------------------------------------------------
@pytest.fixture
def two_member_deal(client):
    """A negotiated deal seating a senior manager and a co-manager at 50 percent."""
    return fx.negotiated_deal_two_members(client)


@pytest.fixture
def allotted_deal(client):
    """A negotiated deal whose worked four-order book has been allotted."""
    return fx.allotted_negotiated_deal(client)


@pytest.fixture
def priced_allotted_deal(client):
    """The allotted deal priced, so takedown credits carry the worked figures."""
    return fx.priced_allotted_negotiated_deal(client)
