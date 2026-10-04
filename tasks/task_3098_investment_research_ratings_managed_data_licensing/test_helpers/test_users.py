"""Pre-built role headers for every role in the PRD (PRD §2.1).

ResearchOps, Analyst, LicenseAdmin and ComplianceOfficer carry opaque user
identifiers. FundCompanyRep's X-User-ID must equal the id of the FundCompany
the rep belongs to, so tests must build those headers per-instance with
make_fund_company_rep_headers(company_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "research_ops_headers": build_user_headers("ops-user-1", "ResearchOps"),
    "analyst_headers": build_user_headers("analyst-1", "Analyst"),
    "license_admin_headers": build_user_headers("lic-admin-1", "LicenseAdmin"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # Fallback only for tests that never reach the issuer check
    # (e.g., authenticated-shape probes); ownership-gated calls MUST use
    # make_fund_company_rep_headers(<FundCompany.id>).
    "fund_company_rep_headers": build_user_headers("rep-1", "FundCompanyRep"),
}


def make_research_ops_headers(user_id: str = "ops-user-1") -> dict:
    return build_user_headers(user_id, "ResearchOps")


def make_analyst_headers(user_id: str) -> dict:
    """Analyst identity is recorded as proposed_by / voter_id."""
    return build_user_headers(user_id, "Analyst")


def make_license_admin_headers(user_id: str = "lic-admin-1") -> dict:
    return build_user_headers(user_id, "LicenseAdmin")


def make_compliance_officer_headers(user_id: str = "compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_fund_company_rep_headers(fund_company_id: str) -> dict:
    """FundCompanyRep: X-User-ID MUST be the FundCompany.id of the issuer
    whenever the call is ownership-gated (raising a dispute)."""
    return build_user_headers(fund_company_id, "FundCompanyRep")
