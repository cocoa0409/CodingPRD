"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. The Member role is entity-backed (X-User-ID must equal the Member
# id) so its shared constant is only a fallback for non-ownership tests.
TEST_USERS = {
    "member_headers": build_user_headers("test-member-1", "Member"),
    "underwriter_headers": build_user_headers("uw-1", "Underwriter"),
    "underwriter2_headers": build_user_headers("uw-2", "Underwriter"),
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
    "adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "adjuster2_headers": build_user_headers("adj-2", "ClaimsAdjuster"),
    "adjuster3_headers": build_user_headers("adj-3", "ClaimsAdjuster"),
    "coordinator_headers": build_user_headers("coord-1", "ClubCoordinator"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity-backed). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter headers with a specific opaque operator id (SoD tests)."""
    return build_user_headers(user_id, "Underwriter")


def make_appraiser_headers(user_id: str) -> dict:
    """Appraiser headers with a specific opaque operator id (SoD tests)."""
    return build_user_headers(user_id, "Appraiser")


def make_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster headers with a specific opaque operator id (SoD tests)."""
    return build_user_headers(user_id, "ClaimsAdjuster")
