"""Pre-built role headers for every role in the PRD (§2.1).

Member and Ambassador are entity-backed roles: for any ownership-gated call
their X-User-ID must equal the acting entity's id, so those headers are built
per-instance via make_member_headers / make_ambassador_headers. The shared
constants are fallbacks for non-ownership tests only. The operator roles are
opaque: any X-User-ID works.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity-backed fallbacks (non-ownership tests only)
    "member_headers": build_user_headers("test-member-1", "Member"),
    "ambassador_headers": build_user_headers("test-ambassador-1", "Ambassador"),
    # opaque operator roles — canonical form
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "partner_manager_headers": build_user_headers("test-partner-manager-1", "PartnerManager"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "compliance_officer_b_headers": build_user_headers("test-co-2", "ComplianceOfficer"),
    "venue_ops_headers": build_user_headers("test-venue-ops-1", "VenueOps"),
}


def make_member_headers(member_id: str) -> dict:
    """For Member (entity-backed by Member): pass the actual Member.id whenever
    the call is ownership-gated (own enrollments, own subscription, own family
    group, own lane verifications, own venue access)."""
    return build_user_headers(member_id, "Member")


def make_ambassador_headers(ambassador_id: str) -> dict:
    """For Ambassador (entity-backed by Ambassador): pass the actual
    Ambassador.id — completing an escort requires the verification's named
    ambassador to match X-User-ID."""
    return build_user_headers(ambassador_id, "Ambassador")


def make_compliance_officer_headers(officer_user_id: str) -> dict:
    """ComplianceOfficer is opaque, but dispute segregation of duties compares
    the resolver's X-User-ID to the opener's, so tests pick explicit ids."""
    return build_user_headers(officer_user_id, "ComplianceOfficer")
