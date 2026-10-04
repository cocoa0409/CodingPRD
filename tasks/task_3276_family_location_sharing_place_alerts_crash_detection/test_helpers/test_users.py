"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise entity-backed ownership checks.
TEST_USERS = {
    # Opaque operator role: shared constant is the canonical form.
    "system_headers": build_user_headers("test-system-operator-1", "System"),
    # Entity-backed roles: fallback constants only for non-ownership tests
    # (400-on-bad-payload, 404-on-missing-resource, etc.).
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "minor_headers": build_user_headers("test-minor-1", "Minor"),
}


# Per-instance builders — required for every entity_backed role. Pass the
# actual Member.id as user_id whenever the call is ownership-gated.
def make_owner_headers(member_id: str) -> dict:
    """For Owner (entity_backed:Member)."""
    return build_user_headers(member_id, "Owner")


def make_admin_headers(member_id: str) -> dict:
    """For Admin (entity_backed:Member)."""
    return build_user_headers(member_id, "Admin")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member)."""
    return build_user_headers(member_id, "Member")


def make_minor_headers(member_id: str) -> dict:
    """For Minor (entity_backed:Member)."""
    return build_user_headers(member_id, "Minor")
