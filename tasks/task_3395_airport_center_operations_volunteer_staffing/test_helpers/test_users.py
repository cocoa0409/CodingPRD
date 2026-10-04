"""Pre-built role headers for every role in the PRD.

Identity semantics (PRD Section 2.1):
- PlatformAdmin / CenterManager / Anonymous carry an opaque X-User-ID that
  is never compared to any entity id (though a manager's id is recorded on
  screenings as claimed_by_user_id / decided_by_user_id).
- Volunteer / Guest are entity-backed: X-User-ID MUST equal the acting
  entity's id. Use make_volunteer_headers(volunteer["id"]) /
  make_guest_headers(guest["id"]) for every ownership-gated call.

Segregation of duties: the manager who claims a screening may not decide
it. The two managers below are therefore distinct by construction; fixtures
always claim as MANAGER_1 and decide as MANAGER_2.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator ids. MANAGER_1 claims screenings, MANAGER_2
# decides them, MANAGER_3 exists for multi-actor probes (e.g. double claim).
PLATFORM_ADMIN_USER_ID = "admin-1"
MANAGER_1_USER_ID = "mgr-1"
MANAGER_2_USER_ID = "mgr-2"
MANAGER_3_USER_ID = "mgr-3"
ANONYMOUS_USER_ID = "anon-1"

TEST_USERS = {
    "admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "manager_headers": build_user_headers(MANAGER_1_USER_ID, "CenterManager"),
    "manager_1_headers": build_user_headers(MANAGER_1_USER_ID, "CenterManager"),
    "manager_2_headers": build_user_headers(MANAGER_2_USER_ID, "CenterManager"),
    "manager_3_headers": build_user_headers(MANAGER_3_USER_ID, "CenterManager"),
    "anonymous_headers": build_user_headers(ANONYMOUS_USER_ID, "Anonymous"),
    # Fallbacks for non-ownership probes only (e.g. role-denial tests).
    "volunteer_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "Volunteer"
    ),
    "guest_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "Guest"
    ),
}


def make_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_manager_headers(user_id: str = MANAGER_1_USER_ID) -> dict:
    """CenterManager (opaque identity). Pass an explicit user_id when the
    call participates in segregation of duties (claim vs decide)."""
    return build_user_headers(user_id, "CenterManager")


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer (entity-backed). user_id MUST be the acting Volunteer's id
    whenever the call is ownership-gated (confirm / cancel / self list)."""
    return build_user_headers(user_id, "Volunteer")


def make_guest_headers(user_id: str) -> dict:
    """Guest (entity-backed). user_id MUST be the acting Guest's id whenever
    the call is ownership-gated (book-for-self / self list)."""
    return build_user_headers(user_id, "Guest")


def make_anonymous_headers(user_id: str = ANONYMOUS_USER_ID) -> dict:
    return build_user_headers(user_id, "Anonymous")
