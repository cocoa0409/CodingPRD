"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "photo_editor_headers": build_user_headers("editor_1", "PhotoEditor"),
    "rights_manager_headers": build_user_headers("rm_ops", "RightsManager"),
    "archivist_headers": build_user_headers("archivist_1", "Archivist"),
    "finance_admin_headers": build_user_headers("finance_1", "FinanceAdmin"),
    "platform_admin_headers": build_user_headers("platform_1", "PlatformAdmin"),
    # Named RightsManager identities for segregation-of-duties scenarios (PRD §3.8).
    "rights_manager_alice_headers": build_user_headers("rm_alice", "RightsManager"),
    "rights_manager_bob_headers": build_user_headers("rm_bob", "RightsManager"),
    # entity_backed:Photographer — fallback for non-ownership tests only.
    "photographer_headers": build_user_headers("test-photographer-1", "Photographer"),
}


def make_photographer_headers(user_id: str) -> dict:
    """For the entity-backed Photographer role: X-User-ID must be the acting
    Photographer record's id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Photographer")


def make_rights_manager_headers(user_id: str) -> dict:
    """RightsManager is an opaque role; distinct user ids matter for the claim
    intake/resolution segregation-of-duties rule (PRD §3.8)."""
    return build_user_headers(user_id, "RightsManager")
