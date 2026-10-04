"""Pre-built role headers for every role the PRD declares (PRD §2.1).

``Member`` and ``UniversityAccountAdmin`` are entity-backed roles: their
``X-User-ID`` must equal the acting ``Member.id`` / ``Account.id`` whenever the
call is ownership-gated, so a per-instance builder is provided for each. The
shared constants below are safe only for calls that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # entity_backed:Member — shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "pod_operator_headers": build_user_headers("test-operator-1", "PodOperator"),
    # entity_backed:Account — shared constant is a fallback for non-ownership tests only.
    "university_account_admin_headers": build_user_headers("test-account-admin-1", "UniversityAccountAdmin"),
    "fleet_admin_headers": build_user_headers("test-fleet-admin-1", "FleetAdmin"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as member_id
    whenever the call is ownership-gated."""
    return build_user_headers(member_id, "Member")


def make_account_admin_headers(account_id: str) -> dict:
    """For UniversityAccountAdmin (entity_backed:Account). Pass the actual Account.id
    as account_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "UniversityAccountAdmin")