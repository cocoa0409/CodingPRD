"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "appointing_executive_headers": build_user_headers(
        "test-appointing-executive-1", "AppointingExecutive"
    ),
    "field_manager_headers": build_user_headers("test-field-manager-1", "FieldManager"),
    # entity_backed:Agency — shared constant is a fallback for non-ownership tests only.
    "agency_principal_headers": build_user_headers("test-agency-principal-1", "AgencyPrincipal"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", "ClaimsAdjuster"),
    "regulatory_board_headers": build_user_headers("test-regulatory-board-1", "RegulatoryBoard"),
    # entity_backed:StaffMember — shared constant is a fallback for non-ownership tests only.
    "staff_member_headers": build_user_headers("test-staff-member-1", "StaffMember"),
}


def make_agency_principal_headers(user_id: str) -> dict:
    """For AgencyPrincipal (entity_backed:Agency). Pass the actual Agency.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AgencyPrincipal")


def make_staff_member_headers(user_id: str) -> dict:
    """For StaffMember (entity_backed:StaffMember). Pass the actual StaffMember.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "StaffMember")