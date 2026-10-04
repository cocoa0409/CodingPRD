"""Pre-built role headers for every role in the PRD.

All roles are opaque (X-User-ID is not tied to any entity's id), so shared
constants are the canonical form. Per-user builders are provided for tests
that key behavior on the caller's id (milestone segregation of duties).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "developer_admin_headers": build_user_headers("dev-admin-1", "DeveloperAdmin"),
    "origination_manager_headers": build_user_headers("origination-1", "OriginationManager"),
    "procurement_lead_headers": build_user_headers("procurement-1", "ProcurementLead"),
    "construction_manager_headers": build_user_headers("cm-1", "ConstructionManager"),
    "tax_counsel_headers": build_user_headers("tc-1", "TaxCounsel"),
    "investor_manager_headers": build_user_headers("investor-1", "InvestorManager"),
    "lender_agent_headers": build_user_headers("lender-1", "LenderAgent"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    "platform_admin_headers": build_user_headers("platform-1", "PlatformAdmin"),
}


def make_construction_manager_headers(user_id: str) -> dict:
    """ConstructionManager headers with a specific X-User-ID (milestone submitter)."""
    return build_user_headers(user_id, "ConstructionManager")


def make_tax_counsel_headers(user_id: str) -> dict:
    """TaxCounsel headers with a specific X-User-ID (milestone certifier)."""
    return build_user_headers(user_id, "TaxCounsel")
