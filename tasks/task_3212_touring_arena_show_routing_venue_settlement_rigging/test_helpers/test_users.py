"""Pre-built role headers for every role in the PRD.

All roles in this domain have opaque identity: X-User-ID is never compared
against any entity id, so shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "tour_manager_headers": build_user_headers("tm-001", "TourManager"),
    "venue_booker_headers": build_user_headers("vb-001", "VenueBooker"),
    "production_engineer_headers": build_user_headers("pe-001", "ProductionEngineer"),
    "production_engineer_b_headers": build_user_headers("pe-002", "ProductionEngineer"),
    "labor_steward_headers": build_user_headers("ls-001", "LaborSteward"),
    "box_office_manager_headers": build_user_headers("bom-001", "BoxOfficeManager"),
    "licensing_manager_headers": build_user_headers("lm-001", "LicensingManager"),
    "compliance_officer_headers": build_user_headers("co-001", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("pa-001", "PlatformAdmin"),
}
