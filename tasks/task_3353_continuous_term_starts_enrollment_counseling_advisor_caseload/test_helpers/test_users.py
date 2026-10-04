"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (SystemAdmin, RegistrarAdmin, ComplianceOfficer,
FinancialAidOfficer) use shared constants. Entity-backed roles (Counselor,
Advisor, Applicant) MUST be built per-instance via the make_* builders with
the actual entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "RegistrarAdmin"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # Two distinct officer identities: certification is segregated from creation.
    "fao1_headers": build_user_headers("officer-1", "FinancialAidOfficer"),
    "fao2_headers": build_user_headers("officer-2", "FinancialAidOfficer"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "counselor_headers": build_user_headers("test-counselor-1", "Counselor"),
    "advisor_headers": build_user_headers("test-advisor-1", "Advisor"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_counselor_headers(staff_id: str) -> dict:
    """Counselor is entity-backed by Staff; pass the real Staff.id."""
    return build_user_headers(staff_id, "Counselor")


def make_advisor_headers(staff_id: str) -> dict:
    """Advisor is entity-backed by Staff; pass the real Staff.id."""
    return build_user_headers(staff_id, "Advisor")


def make_applicant_headers(applicant_id: str) -> dict:
    """Applicant is entity-backed by Applicant; pass the real Applicant.id."""
    return build_user_headers(applicant_id, "Applicant")


def make_fao_headers(officer_id: str) -> dict:
    """FinancialAidOfficer with a chosen opaque id (segregation of duties)."""
    return build_user_headers(officer_id, "FinancialAidOfficer")
