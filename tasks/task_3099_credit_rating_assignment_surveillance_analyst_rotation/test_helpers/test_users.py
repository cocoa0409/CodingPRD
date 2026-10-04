"""Pre-built role headers for every role the PRD declares.

Six roles are opaque (their X-User-ID is an operator identifier not tied to
any persisted row). RatingAnalyst is entity-backed: X-User-ID must be the id
of the acting Analyst, so ownership-gated calls use make_rating_analyst_headers
with the real Analyst id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "engagement_manager_headers": build_user_headers("op-em-1", "EngagementManager"),
    "compliance_officer_headers": build_user_headers("op-co-1", "ComplianceOfficer"),
    "committee_chair_headers": build_user_headers("op-cc-1", "CommitteeChair"),
    "compensation_committee_headers": build_user_headers("op-comp-1", "CompensationCommittee"),
    "anonymous_headers": build_user_headers("op-anon-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("op-pa-1", "PlatformAdmin"),
    # Entity-backed role — shared constant is a fallback for non-ownership calls only.
    "rating_analyst_headers": build_user_headers("op-ra-1", "RatingAnalyst"),
}


def make_rating_analyst_headers(analyst_id: str) -> dict:
    """Headers for RatingAnalyst (entity-backed:Analyst).

    Pass the actual Analyst.id as analyst_id whenever the call is
    ownership-gated (surveillance, review slots, committee votes,
    appearance-reconciliation appeals).
    """
    return build_user_headers(analyst_id, "RatingAnalyst")