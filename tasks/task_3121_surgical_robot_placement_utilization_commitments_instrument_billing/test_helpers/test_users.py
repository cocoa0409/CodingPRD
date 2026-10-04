"""Pre-built role headers for every role in the PRD.

`AccountOwner` and `Surgeon` are entity-backed, so their shared constants are only
safe for calls that are not ownership-gated. Whenever a call is gated on the acting
identity's own resource, build the headers per instance with
`make_account_owner_headers(account["id"])` rather than reaching for the constant.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "regional_sales_director_headers": build_user_headers("rsd-1", "RegionalSalesDirector"),
    "clinical_operations_lead_headers": build_user_headers("col-1", "ClinicalOperationsLead"),
    "hospital_procurement_officer_headers": build_user_headers("hpo-1", "HospitalProcurementOfficer"),
    "service_engineer_headers": build_user_headers("se-1", "ServiceEngineer"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "idn_coordinator_headers": build_user_headers("idn-1", "IDNCoordinator"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed: HospitalAccount — constant is a fallback for non-ownership calls only.
    "account_owner_headers": build_user_headers("account-owner-1", "AccountOwner"),
    # entity_backed: SurgeonTrainingRecord — constant is a fallback for non-ownership calls only.
    "surgeon_headers": build_user_headers("surgeon-1", "Surgeon"),
}


# ─── Per-instance builders for entity_backed roles ───────────────────────────

def make_account_owner_headers(account_id: str) -> dict:
    """AccountOwner headers for the given HospitalAccount id.

    Pass the real `HospitalAccount.id` whenever the call is ownership-gated
    (procedure cases, bulk completion, credentialing evidence).
    """
    return build_user_headers(account_id, "AccountOwner")


def make_surgeon_headers(training_record_id: str) -> dict:
    """Surgeon headers for the given SurgeonTrainingRecord id."""
    return build_user_headers(training_record_id, "Surgeon")


def make_regional_sales_director_headers(region: str) -> dict:
    """RegionalSalesDirector headers whose identity is scoped to `region`.

    Region-scoped roles may only act on accounts whose `region_code` matches.
    """
    return build_user_headers(f"rsd-{region.lower()}", "RegionalSalesDirector")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with a chosen opaque identity (segregation-of-duties tests)."""
    return build_user_headers(user_id, "ComplianceOfficer")