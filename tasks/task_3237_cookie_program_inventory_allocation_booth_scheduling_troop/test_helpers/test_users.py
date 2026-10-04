"""Pre-built role headers for the two roles in the Cookie Program PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The admin constant is canonical (opaque identity). The
# troop-leader constant is a fallback for tests that do NOT exercise troop
# ownership; ownership-gated calls must use make_troop_leader_headers(troop.id).
TEST_USERS = {
    "council_admin_headers": build_user_headers("test-council-admin-1", "CouncilAdmin"),
    "troop_leader_headers": build_user_headers("test-troop-leader-1", "TroopLeader"),
}


def make_council_admin_headers(user_id: str = "test-council-admin-1") -> dict:
    """CouncilAdmin is opaque-identified; any stable id works."""
    return build_user_headers(user_id, "CouncilAdmin")


def make_troop_leader_headers(troop_id: str) -> dict:
    """TroopLeader is entity_backed by Troop: X-User-ID must equal the Troop.id
    whenever the call is ownership-gated."""
    return build_user_headers(troop_id, "TroopLeader")
