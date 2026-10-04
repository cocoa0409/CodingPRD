"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH: the API under test is
already reachable at API_BASE_URL, and ``test_helpers`` is importable as a
top-level package. These fixtures are thin bridges only — entity-backed
identities (AffiliateCoordinator -> Affiliate.id, StateProgramOfficer ->
StateProgram.id) are built per-test with ``make_*_headers`` from
test_helpers, never from the shared fallback constants, whenever the call is
ownership-gated (PRD §2.1).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def state_program_officer_headers():
    """Fallback only — never equals a real StateProgram.id. For ownership-
    gated calls use make_state_program_officer_headers(program["id"])."""
    return TEST_USERS["state_program_officer_headers"]


@pytest.fixture
def affiliate_coordinator_headers():
    """Fallback only — never equals a real Affiliate.id. For ownership-gated
    calls use make_affiliate_coordinator_headers(affiliate["id"])."""
    return TEST_USERS["affiliate_coordinator_headers"]


@pytest.fixture
def advisory_committee_member_headers():
    """Default proposer identity (acm-ada)."""
    return TEST_USERS["advisory_committee_member_headers"]


@pytest.fixture
def advisory_committee_member_2_headers():
    """Default approver identity (acm-ben) — differs from the proposer."""
    return TEST_USERS["advisory_committee_member_2_headers"]


@pytest.fixture
def advisory_committee_member_3_headers():
    """Third committee identity (acm-cid)."""
    return TEST_USERS["advisory_committee_member_3_headers"]


@pytest.fixture
def publisher_ops_headers():
    return TEST_USERS["publisher_ops_headers"]


@pytest.fixture
def mail_ops_headers():
    return TEST_USERS["mail_ops_headers"]
