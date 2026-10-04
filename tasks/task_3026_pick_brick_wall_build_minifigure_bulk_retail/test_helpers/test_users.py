"""Pre-built role headers for every role in the API."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the two opaque roles, and for tests that do not
# exercise member ownership. Both opaque roles carry an operator identifier
# that is never compared against any entity id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    # Fallback only. A member call is ownership-gated, so tests must prefer
    # make_member_headers(member_id) with a real Member id.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(member_id: str) -> dict:
    """For the Member role, whose identifier is the acting member's own id.

    Pass the actual Member id whenever the call targets a member-owned row.
    """
    return build_user_headers(member_id, "Member")


def make_admin_headers(operator_id: str = "test-admin-1") -> dict:
    return build_user_headers(operator_id, "PlatformAdmin")


def make_associate_headers(operator_id: str = "test-associate-1") -> dict:
    return build_user_headers(operator_id, "StoreAssociate")


def anonymous_headers() -> dict:
    """A request with no role header at all."""
    return {"Content-Type": "application/json"}