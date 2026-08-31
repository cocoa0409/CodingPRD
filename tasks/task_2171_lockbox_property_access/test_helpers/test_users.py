"""Pre-built role headers for every role the API recognises."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. AssociationAdmin, SecurityAuditor and LockboxDevice all carry an
# opaque X-User-ID that the server never compares to any entity id, so the shared
# constant is the canonical form for them. The Member entry is a fallback used only by
# tests that never exercise an ownership comparison.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "AssociationAdmin"),
    "auditor_headers": build_user_headers("auditor-1", "SecurityAuditor"),
    "second_auditor_headers": build_user_headers("auditor-2", "SecurityAuditor"),
    "device_headers": build_user_headers("device-gw-1", "LockboxDevice"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}

ADMIN_USER_ID = "admin-1"
AUDITOR_USER_ID = "auditor-1"
SECOND_AUDITOR_USER_ID = "auditor-2"
DEVICE_USER_ID = "device-gw-1"


def make_member_headers(member_id: str) -> dict:
    """For a Member caller. X-User-ID is the id of the acting member record, so every
    ownership-gated call must pass the real member id."""
    return build_user_headers(member_id, "Member")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "AssociationAdmin")


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    return build_user_headers(user_id, "SecurityAuditor")


def make_device_headers(user_id: str = DEVICE_USER_ID) -> dict:
    return build_user_headers(user_id, "LockboxDevice")
