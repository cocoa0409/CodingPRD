"""Pre-built role headers for every role in the PRD (PRD §2.1).

`PlatformAdmin` and `RiskOfficer` carry opaque operator identifiers that are
never compared to a persisted entity's `id`. `ClearingMember` is entity-backed:
its `X-User-ID` must be the `id` of the acting `Participant`, so any
ownership-gated call must use `make_clearing_member_headers(participant_id)`.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # opaque role: shared constant is the canonical form.
    "risk_officer_headers": build_user_headers("test-risk-officer-1", "RiskOfficer"),
    # entity_backed:Participant — shared constant is a fallback for
    # non-ownership tests only (e.g. reads, list calls by a member role).
    "clearing_member_headers": build_user_headers("test-clearing-member-1", "ClearingMember"),
}


def make_clearing_member_headers(user_id: str) -> dict:
    """For ClearingMember (entity_backed:Participant).

    Pass the actual Participant.id as user_id whenever the call is
    ownership-gated — trade submission, lock-in, dispute, deposit postings,
    settlement funding, affirmation and sealed bidding.
    """
    return build_user_headers(user_id, "ClearingMember")