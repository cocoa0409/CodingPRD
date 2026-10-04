"""Pre-built role headers for every role in the PRD (section 2.1).

MemberAdmin and DonationAttendant are entity-backed: their X-User-ID must equal
the id of the MemberOrg / DonationSite being acted on. Always build their
headers with the per-instance builders below. The other eight roles are opaque
and safe to use as shared constants."""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "brand_regulator_headers": build_user_headers("test-brand-regulator-1", "BrandRegulator"),
    # Entity-backed roles: shared constants are a fallback for non-ownership
    # tests ONLY (their X-User-ID matches no real entity id).
    "member_admin_headers": build_user_headers("test-member-admin-1", "MemberAdmin"),
    "donation_attendant_headers": build_user_headers("test-attendant-1", "DonationAttendant"),
    "store_associate_headers": build_user_headers("test-store-associate-1", "StoreAssociate"),
    "production_lead_headers": build_user_headers("test-production-lead-1", "ProductionLead"),
    "program_director_headers": build_user_headers("pd-1", "ProgramDirector"),
    "member_cfo_headers": build_user_headers("cfo-1", "MemberCFO"),
    "contract_manager_headers": build_user_headers("cm-1", "ContractManager"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
}


def make_member_admin_headers(org_id: str) -> dict:
    """MemberAdmin is entity-backed: X-User-ID must equal the MemberOrg id."""
    return build_user_headers(org_id, "MemberAdmin")


def make_donation_attendant_headers(site_id: str) -> dict:
    """DonationAttendant is entity-backed: X-User-ID must equal the DonationSite id."""
    return build_user_headers(site_id, "DonationAttendant")


def make_program_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_member_cfo_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MemberCFO")


def make_contract_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_store_associate_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StoreAssociate")


def make_production_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionLead")
