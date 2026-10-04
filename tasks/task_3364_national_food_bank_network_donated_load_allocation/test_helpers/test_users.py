"""Pre-built role headers for every role declared in the PRD.

`MemberFoodBank` is entity-backed: `X-User-ID` is the acting member's own
`id`, so every ownership-gated call MUST use `make_member_headers(member["id"])`
rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for calls that do not depend on
# the caller owning the subject resource.
TEST_USERS = {
    "admin_headers": build_user_headers("ops_admin_1", "NetworkAdmin"),
    "auditor_headers": build_user_headers("auditor_7", "NetworkAuditor"),
    # Entity-backed role: fallback only for non-ownership-gated calls.
    "member_headers": build_user_headers("member-shared-placeholder", "MemberFoodBank"),
}

# Distinct operator identities used by the segregation-of-duties rules.
ADMIN_OPERATOR_ID = "ops_admin_1"
SECOND_ADMIN_OPERATOR_ID = "ops_admin_2"
AUDITOR_OPERATOR_ID = "auditor_7"


def make_member_headers(user_id: str) -> dict:
    """Headers for a MemberFoodBank caller acting as the member `user_id`.

    Pass the actual MemberFoodBank.id whenever the call is ownership-gated
    (bidding, scheduling, collecting, withdrawing).
    """
    return build_user_headers(user_id, "MemberFoodBank")


def make_admin_headers(user_id: str = ADMIN_OPERATOR_ID) -> dict:
    """Headers for a NetworkAdmin operator (identity is opaque)."""
    return build_user_headers(user_id, "NetworkAdmin")


def make_auditor_headers(user_id: str = AUDITOR_OPERATOR_ID) -> dict:
    """Headers for a NetworkAuditor operator (identity is opaque)."""
    return build_user_headers(user_id, "NetworkAuditor")
