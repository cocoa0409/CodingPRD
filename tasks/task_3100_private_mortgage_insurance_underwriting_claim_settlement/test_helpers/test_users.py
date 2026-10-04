"""Pre-built role headers for every role in the PRD.

`MasterPolicyAdmin`, `Underwriter` and `Borrower` are opaque identities: the
shared constant is the canonical form. `Lender` and `Servicer` are
entity-backed: `X-User-ID` is compared against the owning row's `id`, so any
ownership-gated call must use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "MasterPolicyAdmin"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "borrower_headers": build_user_headers("borrower-42", "Borrower"),
    # entity_backed: shared constants are fallbacks for non-ownership tests only.
    "lender_headers": build_user_headers("test-lender-placeholder", "Lender"),
    "servicer_headers": build_user_headers("test-servicer-placeholder", "Servicer"),
}


def make_lender_headers(lender_id: str) -> dict:
    """For Lender (entity_backed:Lender). Pass the actual Lender.id whenever the
    call is ownership-gated."""
    return build_user_headers(lender_id, "Lender")


def make_servicer_headers(servicer_id: str) -> dict:
    """For Servicer (entity_backed:Servicer). Pass the actual Servicer.id whenever
    the call is ownership-gated."""
    return build_user_headers(servicer_id, "Servicer")