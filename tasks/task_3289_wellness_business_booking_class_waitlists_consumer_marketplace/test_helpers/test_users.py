"""Pre-built role headers for every role the platform declares.

``StudioOwner``, ``Client`` and ``StaffMember`` are entity-backed: their
``X-User-ID`` is the ``id`` of the acting entity, so any ownership-gated call
must use the per-instance builder with the real entity id rather than the
shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque roles and for calls whose success does
# not depend on owning the subject resource.
TEST_USERS = {
    "operator_headers": build_user_headers("test-operator-1", "OperatorOnly"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # entity-backed shared constants — fallback for non-ownership tests only.
    "studio_owner_headers": build_user_headers("test-studio-owner-1", "StudioOwner"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "staff_member_headers": build_user_headers("test-staff-member-1", "StaffMember"),
}

# No user context at all — used to exercise the missing-header rejection.
NO_CONTEXT_HEADERS: dict = {}


def make_studio_owner_headers(studio_id: str) -> dict:
    """For StudioOwner (entity_backed:Studio). Pass the acting Studio.id so the
    studio-ownership comparison binds to a real entity."""
    return build_user_headers(studio_id, "StudioOwner")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the acting Client.id so reads and
    writes scoped to that client bind to a real entity."""
    return build_user_headers(client_id, "Client")


def make_staff_member_headers(staff_id: str) -> dict:
    """For StaffMember (entity_backed:StaffMember). Pass the acting StaffMember.id."""
    return build_user_headers(staff_id, "StaffMember")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """PlatformAdmin is opaque; this exists for symmetry and is exempt from the
    studio-ownership comparison."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    """OperatorOnly is opaque and owns only the logical clock and injectors."""
    return build_user_headers(user_id, "OperatorOnly")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    """Anonymous is opaque: an unauthenticated marketplace browser."""
    return build_user_headers(user_id, "Anonymous")