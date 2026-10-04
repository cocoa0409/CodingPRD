"""Pre-built role headers for every role in the program (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# OpsAdmin and Distributor are opaque identities: X-User-ID is not compared to
# any persisted entity's id, so the shared constant is the canonical form for
# these roles.
#
# StoreOrganizer and Judge are entity-backed: X-User-ID must be the id of a real
# Store / JudgeCertification whenever the call is ownership-gated. The shared
# constants below are placeholders for calls that do not exercise ownership
# (bad-payload 400s, missing-resource 404s, reads); ownership-gated fixtures MUST
# use the per-instance builders.
TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-operator-1", "OpsAdmin"),
    "distributor_headers": build_user_headers("test-distributor-1", "Distributor"),
    "store_organizer_headers": build_user_headers("test-store-organizer-1", "StoreOrganizer"),
    "judge_headers": build_user_headers("JUDGE-FALLBACK", "Judge"),
}


def make_ops_admin_headers(user_id: str = "test-operator-1") -> dict:
    """OpsAdmin is an opaque role; the id is recorded but never entity-checked."""
    return build_user_headers(user_id, "OpsAdmin")


def make_distributor_headers(user_id: str = "test-distributor-1") -> dict:
    """Distributor is an opaque role; the id is recorded but never entity-checked."""
    return build_user_headers(user_id, "Distributor")


def make_store_organizer_headers(store_id: str) -> dict:
    """For StoreOrganizer (entity-backed: Store). Pass the acting Store.id as
    user_id on every ownership-gated call."""
    return build_user_headers(store_id, "StoreOrganizer")


def make_judge_headers(judge_ref: str) -> dict:
    """For Judge (entity-backed: JudgeCertification). Pass the acting
    JudgeCertification's reference as user_id."""
    return build_user_headers(judge_ref, "Judge")