"""Pre-built role headers for the eight roles in the PRD (section 2.1).

Identity semantics (PRD section 2.1):
- CompanyRepresentative: X-User-ID IS the acting SubjectCompany's id
  (entity-backed). Ownership checks compare it to the resource's company FK.
- Claimant: X-User-ID IS the acting Claimant's id (entity-backed).
- The other six roles are opaque operator identifiers; the server records but
  never compares them to entity ids, EXCEPT under segregation-of-duties rules
  (penalty confirm/waive vs assessor; check issue vs claim approver).

Because several assertions in the design indices pin the literal operator ids
"fa-1" (FundAdministrator approver), "cm-1"/"cm-2" (ComplianceMonitor
assessor/confirmer pair), and "do-1" (DisbursementOfficer issuer), the shared
constants below use exactly those ids.

Shared constants are safe for opaque roles and for non-ownership tests.
For entity-backed roles, ALWAYS use make_company_representative_headers(
company["id"]) / make_claimant_headers(claimant["id"]) when the call is
ownership-gated (CID respond/quash, compliance-report submit/resubmit,
judgment payment, penalty PAID, claim filing).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — canonical shared form.
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "staff_attorney_headers": build_user_headers("sa-1", "StaffAttorney"),
    "commissioner_headers": build_user_headers("comm-1", "Commissioner"),
    # Two ComplianceMonitors: segregation of duties requires the
    # confirming/waiving monitor to differ from the assessing monitor.
    "compliance_monitor_headers": build_user_headers("cm-1", "ComplianceMonitor"),
    "compliance_monitor_2_headers": build_user_headers("cm-2", "ComplianceMonitor"),
    # Two FundAdministrators: lets a test choose a distinct approver per claim.
    "fund_administrator_headers": build_user_headers("fa-1", "FundAdministrator"),
    "fund_administrator_2_headers": build_user_headers("fa-2", "FundAdministrator"),
    # Two DisbursementOfficers: the check issuer must differ from the claim
    # approver; do-1 is the default issuer, do-2 a spare.
    "disbursement_officer_headers": build_user_headers("do-1", "DisbursementOfficer"),
    "disbursement_officer_2_headers": build_user_headers("do-2", "DisbursementOfficer"),
    # Entity-backed roles — FALLBACK ONLY for tests that do not exercise
    # ownership (e.g. RBAC denials, 400/404 probes). These ids deliberately
    # match no real entity id.
    "company_representative_headers": build_user_headers("test-company-rep-1", "CompanyRepresentative"),
    "claimant_headers": build_user_headers("test-claimant-1", "Claimant"),
}


def make_platform_admin_headers(user_id: str = "pa-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_staff_attorney_headers(user_id: str = "sa-1") -> dict:
    return build_user_headers(user_id, "StaffAttorney")


def make_commissioner_headers(user_id: str = "comm-1") -> dict:
    return build_user_headers(user_id, "Commissioner")


def make_compliance_monitor_headers(user_id: str) -> dict:
    """Pass distinct ids for the assessor and the confirmer/waiver."""
    return build_user_headers(user_id, "ComplianceMonitor")


def make_fund_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FundAdministrator")


def make_disbursement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DisbursementOfficer")


def make_company_representative_headers(company_id: str) -> dict:
    """CompanyRepresentative is entity-backed: pass the SubjectCompany's id
    whenever the call is ownership-gated (CID RESPONDED/QUASH_PETITIONED,
    compliance-report create/resubmit, judgment payments, penalty PAID)."""
    return build_user_headers(company_id, "CompanyRepresentative")


def make_claimant_headers(claimant_id: str) -> dict:
    """Claimant is entity-backed: pass the Claimant's id whenever the call is
    ownership-gated (POST /enforcement/claims requires X-User-ID == claimant_id)."""
    return build_user_headers(claimant_id, "Claimant")
