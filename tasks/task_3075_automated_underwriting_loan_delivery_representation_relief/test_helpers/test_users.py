"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership checks.
TEST_USERS = {
    "gse_admin_headers": build_user_headers("gse-admin-1", "GseAdmin"),
    "gse_admin_2_headers": build_user_headers("gse-admin-2", "GseAdmin"),
    "gse_admin_3_headers": build_user_headers("gse-admin-3", "GseAdmin"),
    "underwriter_headers": build_user_headers("underwriter-1", "Underwriter"),
    "uw_engine_headers": build_user_headers("uw-engine-1", "GseUnderwritingEngine"),
    "qc_auditor_headers": build_user_headers("qc-auditor-1", "QcAuditor"),
    # Fallbacks for non-ownership tests only — entity_backed roles must use
    # the builders below when the call is ownership-gated.
    "seller_officer_headers": build_user_headers("test-seller-officer-1", "SellerOfficer"),
    "servicer_officer_headers": build_user_headers("test-servicer-officer-1", "ServicerOfficer"),
}


def make_seller_officer_headers(user_id: str) -> dict:
    """For SellerOfficer (entity_backed: Seller). Pass the actual Seller.id as
    user_id whenever the call is ownership-gated (e.g. loan delivery)."""
    return build_user_headers(user_id, "SellerOfficer")


def make_servicer_officer_headers(user_id: str) -> dict:
    """For ServicerOfficer (entity_backed: Servicer). Pass the actual Servicer.id
    as user_id whenever the call is ownership-gated (e.g. payment events)."""
    return build_user_headers(user_id, "ServicerOfficer")
