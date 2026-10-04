"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "planner_headers": build_user_headers("test-planner-1", "UtilityPlanner"),
    "commissioner_headers": build_user_headers("test-commissioner-1", "Commissioner"),
    # entity_backed:Intervenor — fallback for non-ownership tests only.
    "intervener_headers": build_user_headers("test-intervener-1", "Intervener"),
    "commenter_headers": build_user_headers("test-commenter-1", "PublicCommenter"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UtilityPlanner")


def make_commissioner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Commissioner")


def make_intervener_headers(intervenor_id: str) -> dict:
    """For Intervener (entity_backed:Intervenor). Pass the actual Intervenor.id
    whenever the call is ownership-gated (testimony file/withdraw/refile)."""
    return build_user_headers(intervenor_id, "Intervener")


def make_commenter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PublicCommenter")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
