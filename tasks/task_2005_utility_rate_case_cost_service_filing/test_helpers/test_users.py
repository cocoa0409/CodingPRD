"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque-role operator ids recorded by transitions (e.g. Adjustment
# proposed_by_user_id / verified_by_user_id in PRD §3.2).
UF_ALICE = "uf_alice"
UF_BOB = "uf_bob"
STAFF_USER = "staff_main"
ALJ_USER = "alj_main"

# Shared constants — safe for opaque roles, and for tests that do not exercise
# IntervenorRep ownership.
TEST_USERS = {
    "utility_filer_alice": build_user_headers(UF_ALICE, "UtilityFiler"),
    "utility_filer_bob": build_user_headers(UF_BOB, "UtilityFiler"),
    "commission_staff": build_user_headers(STAFF_USER, "CommissionStaff"),
    "alj": build_user_headers(ALJ_USER, "ALJ"),
    # Fallback only for IntervenorRep calls that are NOT ownership-gated
    # (e.g. party self-registration, or role-denied probes).
    "intervenor_rep": build_user_headers("ir_placeholder", "IntervenorRep"),
}


def make_intervenor_rep_headers(intervenor_id: str) -> dict:
    """IntervenorRep is entity-backed (PRD §2.1): X-User-ID must equal the
    acting Intervenor's id on every ownership-gated call."""
    return build_user_headers(intervenor_id, "IntervenorRep")


def make_utility_filer_headers(user_id: str) -> dict:
    """UtilityFiler is opaque; the id is recorded by Adjustment transitions."""
    return build_user_headers(user_id, "UtilityFiler")


def make_commission_staff_headers(user_id: str = STAFF_USER) -> dict:
    return build_user_headers(user_id, "CommissionStaff")


def make_alj_headers(user_id: str = ALJ_USER) -> dict:
    return build_user_headers(user_id, "ALJ")
