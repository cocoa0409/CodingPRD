"""Pre-built role headers for every role in the PRD (§2.1).

For every role except HospitalPartner, X-User-ID is an opaque operator
identifier. For HospitalPartner, X-User-ID is the id of the acting
SourceOrganization, so ownership-gated calls must use
``make_hospital_partner_headers(org_id)`` with the real org id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise HospitalPartner ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "portfolio_analyst_headers": build_user_headers("analyst-1", "PortfolioAnalyst"),
    "eligibility_officer_headers": build_user_headers("eo-1", "EligibilityOfficer"),
    "contract_manager_headers": build_user_headers("cm-1", "ContractManager"),
    "finance_officer_headers": build_user_headers("fin-9", "FinanceOfficer"),
    "donor_relations_headers": build_user_headers("dro-1", "DonorRelationsOfficer"),
    "compliance_auditor_headers": build_user_headers("ca-1", "ComplianceAuditor"),
    # Fallback for non-ownership HospitalPartner calls only.
    "hospital_partner_headers": build_user_headers("hp-1", "HospitalPartner"),
}


def make_platform_admin_headers(user_id="admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_portfolio_analyst_headers(user_id="analyst-1") -> dict:
    return build_user_headers(user_id, "PortfolioAnalyst")


def make_eligibility_officer_headers(user_id="eo-1") -> dict:
    return build_user_headers(user_id, "EligibilityOfficer")


def make_contract_manager_headers(user_id="cm-1") -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_finance_officer_headers(user_id="fin-9") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_donor_relations_headers(user_id="dro-1") -> dict:
    return build_user_headers(user_id, "DonorRelationsOfficer")


def make_compliance_auditor_headers(user_id="ca-1") -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_hospital_partner_headers(user_id: str) -> dict:
    """For HospitalPartner (entity-backed by SourceOrganization). Pass the
    acting organization's id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "HospitalPartner")
