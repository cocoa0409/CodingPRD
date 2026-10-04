"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership. Entity-backed roles use the builders below whenever
# the downstream call is ownership-gated.
TEST_USERS = {
    # opaque role: the shared constant is the canonical form.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # opaque role: a platform operator id is never compared to any entity id.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed:Member — shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed:HostBusiness — shared constant is a fallback for non-ownership tests only.
    "host_operator_headers": build_user_headers("test-host-1", "HostOperator"),
}

# An unrecognized role, used to exercise the authentication gate.
UNKNOWN_ROLE_HEADERS = build_user_headers("test-unknown-1", "CuriousVisitor")


# ---------------------------------------------------------------------------
# Per-instance builders — required for every entity_backed role.
# ---------------------------------------------------------------------------

def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_host_operator_headers(user_id: str) -> dict:
    """For HostOperator (entity_backed:HostBusiness). Pass the actual
    HostBusiness.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "HostOperator")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """For Anonymous (opaque identity)."""
    return build_user_headers(user_id, "Anonymous")