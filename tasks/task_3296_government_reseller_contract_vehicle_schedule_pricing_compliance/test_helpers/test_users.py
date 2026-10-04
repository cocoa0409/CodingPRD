"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles use opaque operator identifiers: X-User-ID is never compared
to an entity primary key, only to other operator identifiers (for
segregation-of-duties checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "contracts_manager_headers": build_user_headers("test-contracts-manager-1", "ContractsManager"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "reseller_ops_headers": build_user_headers("test-reseller-ops-1", "ResellerOps"),
    "integrator_headers": build_user_headers("test-integrator-1", "Integrator"),
    "finance_ops_headers": build_user_headers("test-finance-ops-1", "FinanceOps"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_contracts_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractsManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_reseller_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ResellerOps")


def make_integrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Integrator")


def make_finance_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOps")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
