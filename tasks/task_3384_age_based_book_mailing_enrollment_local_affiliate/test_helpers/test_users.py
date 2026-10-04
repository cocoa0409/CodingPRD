"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: an AffiliateCoordinator's X-User-ID IS the id of
the Affiliate they run, and a StateProgramOfficer's X-User-ID IS the id of the
StateProgram they serve. For any ownership-gated call, tests and fixtures MUST
build headers with ``make_affiliate_coordinator_headers(affiliate["id"])`` /
``make_state_program_officer_headers(program["id"])`` — the shared constants
below are only safe for tests whose outcome does not depend on ownership
(shape rejections, not-found probes, role-denial checks) or for the four
opaque roles.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import ACM_APPROVER_ID, ACM_PROPOSER_ID, ACM_THIRD_ID
from .types import UserRole

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form (PRD §2.1: the
    # server records but never matches these ids against entities).
    "platform_admin_headers": build_user_headers("test-platform-admin-1", UserRole.PLATFORM_ADMIN.value),
    # AdvisoryCommitteeMember is opaque, but segregation of duties (PRD §3.5)
    # needs three distinct committee identities: proposer / approver / third.
    "advisory_committee_member_headers": build_user_headers(
        ACM_PROPOSER_ID, UserRole.ADVISORY_COMMITTEE_MEMBER.value
    ),
    "advisory_committee_member_2_headers": build_user_headers(
        ACM_APPROVER_ID, UserRole.ADVISORY_COMMITTEE_MEMBER.value
    ),
    "advisory_committee_member_3_headers": build_user_headers(
        ACM_THIRD_ID, UserRole.ADVISORY_COMMITTEE_MEMBER.value
    ),
    "publisher_ops_headers": build_user_headers("test-publisher-ops-1", UserRole.PUBLISHER_OPS.value),
    "mail_ops_headers": build_user_headers("test-mail-ops-1", UserRole.MAIL_OPS.value),
    # Entity-backed roles — FALLBACK ONLY for non-ownership tests. The id
    # strings below belong to no real entity, so any ownership check rejects
    # them; see module docstring.
    "affiliate_coordinator_headers": build_user_headers(
        "test-affiliate-coordinator-1", UserRole.AFFILIATE_COORDINATOR.value
    ),
    "state_program_officer_headers": build_user_headers(
        "test-state-program-officer-1", UserRole.STATE_PROGRAM_OFFICER.value
    ),
}


def make_affiliate_coordinator_headers(affiliate_id: str) -> dict:
    """AffiliateCoordinator is entity_backed:Affiliate — pass the actual
    Affiliate.id whenever the call is ownership-gated (children, address
    changes, population stats, invoice pay/dispute, scoped reads)."""
    return build_user_headers(affiliate_id, UserRole.AFFILIATE_COORDINATOR.value)


def make_state_program_officer_headers(state_program_id: str) -> dict:
    """StateProgramOfficer is entity_backed:StateProgram — pass the actual
    StateProgram.id whenever approving/rejecting that program's agreements."""
    return build_user_headers(state_program_id, UserRole.STATE_PROGRAM_OFFICER.value)


def make_advisory_committee_member_headers(user_id: str) -> dict:
    """Opaque role; distinct member ids exercise segregation of duties."""
    return build_user_headers(user_id, UserRole.ADVISORY_COMMITTEE_MEMBER.value)


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_publisher_ops_headers(user_id: str = "test-publisher-ops-1") -> dict:
    return build_user_headers(user_id, UserRole.PUBLISHER_OPS.value)


def make_mail_ops_headers(user_id: str = "test-mail-ops-1") -> dict:
    return build_user_headers(user_id, UserRole.MAIL_OPS.value)


__all__ = [
    "TEST_USERS",
    "make_affiliate_coordinator_headers",
    "make_state_program_officer_headers",
    "make_advisory_committee_member_headers",
    "make_platform_admin_headers",
    "make_publisher_ops_headers",
    "make_mail_ops_headers",
]
