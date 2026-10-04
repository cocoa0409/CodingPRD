"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The Member shared constant is only safe for tests that do
# not exercise ownership; any Member-scoped mutation must use
# make_member_headers(<the Member record's id>) — X-User-ID must equal the
# member's id for ownership checks to pass.
TEST_USERS = {
    "member_headers": build_user_headers("test-member-1", "Member"),
    "associate_headers": build_user_headers("test-associate-1", "Associate"),
    "lpo_headers": build_user_headers("test-lpo-1", "LossPreventionOfficer"),
    "club_manager_headers": build_user_headers("test-club-manager-1", "ClubManager"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_member_headers(member_id: str) -> dict:
    """Member role is entity-backed: pass the actual Member record's id
    whenever the call is ownership-gated (session pay/scan/abandon/exit-scan,
    curbside pickup/cancel/reschedule)."""
    return build_user_headers(member_id, "Member")


def make_associate_headers(user_id: str) -> dict:
    """Associate identity is opaque; pass a distinct id when attribution
    matters (intercept associate_id, verification flagging_associate_id,
    staged_by_associate_id)."""
    return build_user_headers(user_id, "Associate")


def make_lpo_headers(user_id: str) -> dict:
    """LossPreventionOfficer identity is opaque; pass a distinct id when
    segregation-of-duties attribution matters."""
    return build_user_headers(user_id, "LossPreventionOfficer")


def make_club_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClubManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
