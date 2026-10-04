"""Pre-built role headers for every role in the PRD (section 2.1 RBAC)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants -- safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    # Ownership-gated calls MUST use make_member_headers(member["id"]) instead.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # opaque roles: shared constants are the canonical form.
    "partner_admin_headers": build_user_headers("test-partner-admin-1", "PartnerAdmin"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (identity entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated -- folder visibility, connection
    reauthorize/disconnect, or any call whose success depends on the caller
    owning the subject resource."""
    return build_user_headers(user_id, "Member")


def anonymous_headers() -> dict:
    """Headers with no role declared -- used for the unauthenticated-request claim."""
    return {"Content-Type": "application/json"}


def wrong_role_headers() -> dict:
    """Headers naming a role outside the four the platform recognizes."""
    return {"X-User-ID": "test-nobody-1", "X-User-Role": "SuperUser",
            "Content-Type": "application/json"}