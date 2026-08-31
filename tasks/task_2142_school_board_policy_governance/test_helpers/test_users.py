"""Pre-built role headers for every governance role."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the six opaque roles, whose X-User-ID is never
# compared to any entity id, and for tests that never exercise ownership.
TEST_USERS = {
    "board_clerk_headers": build_user_headers("clerk-ops-1", "BoardClerk"),
    "policy_analyst_headers": build_user_headers("analyst-ops-1", "PolicyAnalyst"),
    "superintendent_headers": build_user_headers("supt-ops-1", "Superintendent"),
    "school_principal_headers": build_user_headers("principal-ops-1", "SchoolPrincipal"),
    "legal_update_service_headers": build_user_headers("lus-feed-1", "LegalUpdateService"),
    "public_headers": build_user_headers("public-visitor-1", "Public"),
    # The two entity-backed roles: these shared constants are only a fallback
    # for calls that perform no ownership check at all.
    "board_president_headers": build_user_headers("president-placeholder", "BoardPresident"),
    "board_member_headers": build_user_headers("member-placeholder", "BoardMember"),
}


def make_board_president_headers(board_member_id: str) -> dict:
    """BoardPresident is entity-backed: X-User-ID is the acting trustee's id."""
    return build_user_headers(board_member_id, "BoardPresident")


def make_board_member_headers(board_member_id: str) -> dict:
    """BoardMember is entity-backed: X-User-ID is the acting trustee's id."""
    return build_user_headers(board_member_id, "BoardMember")
