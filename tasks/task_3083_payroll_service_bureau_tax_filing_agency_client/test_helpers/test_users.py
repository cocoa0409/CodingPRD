"""Pre-built role headers for every role in the PRD (§2.1).

ClientPayrollAdmin is entity-backed: its X-User-ID must equal the id of the
Client aggregate being touched, so fixtures MUST build its headers per
instance via make_client_admin_headers(client["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "onboarder_headers": build_user_headers("onboarder-1", "BureauOnboarder"),
    "treasury_headers": build_user_headers("treasury-1", "BureauTreasury"),
    "compliance_headers": build_user_headers("compliance-1", "BureauCompliance"),
    # Tax filer is opaque but segregation of duties is per-X-User-ID, so two
    # distinct filer identities are provided.
    "filer_alpha_headers": build_user_headers("filer-alpha", "BureauTaxFiler"),
    "filer_beta_headers": build_user_headers("filer-beta", "BureauTaxFiler"),
    # Entity-backed role fallback for non-ownership probes only.
    "client_admin_headers": build_user_headers(
        "client-admin-unknown", "ClientPayrollAdmin"
    ),
}


def make_client_admin_headers(client_id: str) -> dict:
    """Headers for ClientPayrollAdmin acting on client `client_id`.

    Required for every ownership-gated call — X-User-ID must equal the
    client aggregate's id (PRD §2.1).
    """
    return build_user_headers(client_id, "ClientPayrollAdmin")


def make_filer_headers(user_id: str) -> dict:
    """Headers for a BureauTaxFiler with a specific opaque user id."""
    return build_user_headers(user_id, "BureauTaxFiler")
