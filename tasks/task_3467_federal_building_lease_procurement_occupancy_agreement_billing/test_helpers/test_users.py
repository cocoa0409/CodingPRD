"""Pre-built role headers for every role in the PRD (§2.1).

GSAAdmin / GSALeasingOfficer / GSAPropertyManager / LessorRep identities are
opaque operator identifiers. AgencyManager is entity-backed: X-User-ID must be
the acting Agency's id whenever the call is ownership-gated — use
make_agency_manager_headers(agency_id) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "gsa_admin_headers": build_user_headers("test-gsa-admin-1", "GSAAdmin"),
    "gsa_leasing_officer_headers": build_user_headers(
        "test-gsa-leasing-officer-1", "GSALeasingOfficer"),
    "gsa_property_manager_headers": build_user_headers(
        "test-gsa-property-manager-1", "GSAPropertyManager"),
    # Fallback for non-ownership contexts only; ownership-gated calls MUST use
    # make_agency_manager_headers(<agency id>).
    "agency_manager_headers": build_user_headers("test-agency-1", "AgencyManager"),
    "lessor_rep_headers": build_user_headers("test-lessor-rep-1", "LessorRep"),
}


def make_agency_manager_headers(agency_id: str) -> dict:
    """AgencyManager is entity-backed by Agency: X-User-ID == the agency's id."""
    return build_user_headers(agency_id, "AgencyManager")
