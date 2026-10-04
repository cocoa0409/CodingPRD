"""Pre-built role headers for every role in the PRD (§2.1).

ConversionTechnician is entity-backed: its X-User-ID must be the acting
Technician's id whenever a call is ownership-gated (event start/complete/
cancel/unstart). Use make_conversion_technician_headers(technician_id) for
those calls; the shared constant is only safe for role-denial tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "site_manager_headers": build_user_headers("test-site-manager-1", "SiteManager"),
    "safety_officer_headers": build_user_headers("test-safety-officer-1", "SafetyOfficer"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    # entity_backed:Technician — fallback for non-ownership tests only
    "conversion_technician_headers": build_user_headers("test-conversion-tech-1", "ConversionTechnician"),
    "billing_operator_headers": build_user_headers("test-billing-operator-1", "BillingOperator"),
}

# A request with no X-User-Role header at all (PRD §2.1 authentication stage)
ANONYMOUS_HEADERS = {"X-User-ID": "test-anonymous-1"}


def make_conversion_technician_headers(technician_id: str) -> dict:
    """For ConversionTechnician (entity_backed:Technician). Pass the actual
    Technician.id whenever the call is ownership-gated."""
    return build_user_headers(technician_id, "ConversionTechnician")
