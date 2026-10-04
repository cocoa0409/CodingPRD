"""Pre-built role headers for every role in the PRD.

All roles are opaque: X-User-ID is not compared to any entity id, so shared
constants are canonical. Distinct user ids still matter for segregation-of-
duties checks (submitter vs acceptor, reconciler vs acceptor), so dedicated
per-user ids are provided for those flows.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "procurement_officer": build_user_headers("procurement-officer-1", "ProcurementOfficer"),
    "implementation_manager": build_user_headers("impl-manager-1", "ImplementationManager"),
    "agency_pm": build_user_headers("agency-pm-9", "AgencyProjectManager"),
    "vendor_pm": build_user_headers("vendor-pm-1", "VendorProjectManager"),
    "finance_officer": build_user_headers("finance-officer-1", "FinanceOfficer"),
    "business_analyst": build_user_headers("business-analyst-1", "BusinessAnalyst"),
    "data_migration_lead": build_user_headers("dml-1", "DataMigrationLead"),
    "interface_engineer": build_user_headers("iface-eng-1", "InterfaceEngineer"),
    "support_manager": build_user_headers("support-mgr-1", "SupportManager"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build auth headers for an arbitrary user id under a catalog role."""
    return build_user_headers(user_id, role)
