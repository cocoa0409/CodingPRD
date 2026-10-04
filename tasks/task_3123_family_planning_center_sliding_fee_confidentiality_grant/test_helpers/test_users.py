"""Pre-built role headers for every role in the PRD.

All seven roles in this system use opaque operator identifiers (PRD §2.1):
no role is entity-backed, so the shared constants below are the canonical
form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "grant_admin_headers": build_user_headers("test-grant-admin-1", "GrantAdministrator"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDeskStaff"),
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    "billing_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    "care_coordinator_headers": build_user_headers("test-care-coord-1", "CareCoordinator"),
    "supply_coordinator_headers": build_user_headers("test-supply-coord-1", "SupplyCoordinator"),
    "privacy_officer_headers": build_user_headers("test-privacy-officer-1", "PrivacyOfficer"),
}
