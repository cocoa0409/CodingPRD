"""Pre-built role headers for every role in the PRD.

WholesalerPrincipal is entity-backed: its X-User-ID must equal the acting
Wholesaler's ``id`` on every ownership-gated call, so fixtures and tests MUST
build headers with ``make_wholesaler_headers(wholesaler["id"])``. The shared
``wholesaler_headers`` constant exists only as a fallback for tests whose
outcome does not depend on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "BrewerAdmin"),
    "compliance_headers": build_user_headers("test-compliance-1", "BrewerCompliance"),
    "auditor_headers": build_user_headers("test-auditor-1", "DraftAuditor"),
    # Fallback only — never use for ownership-gated calls.
    "wholesaler_headers": build_user_headers("test-wholesaler-1", "WholesalerPrincipal"),
}


def make_wholesaler_headers(wholesaler_id: str) -> dict:
    """Headers for a WholesalerPrincipal acting as the given Wholesaler.

    Required whenever the call is ownership-gated (transfer create,
    rofr-response, allocation request, assignment decision, review response,
    plan revise, promotion opt-in).
    """
    return build_user_headers(wholesaler_id, "WholesalerPrincipal")
