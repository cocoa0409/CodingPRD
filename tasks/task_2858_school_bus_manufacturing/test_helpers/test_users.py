"""Pre-built role headers for every role named in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Pinned opaque identities. Five of the six roles are opaque: the API treats
# X-User-ID as an arbitrary label, so a shared constant is the canonical form.
# `DealerAgent` is different — its X-User-ID must be the id of the Dealer row
# acting, so it has no meaningful shared constant and must be built per dealer.
SALES_ENGINEER_USER_ID = "sales-01"
CONTRACTS_ADMIN_USER_ID = "contracts-01"
CONTRACTS_ADMIN_2_USER_ID = "contracts-02"
PLANT_SCHEDULER_USER_ID = "plant-01"
QUALITY_INSPECTOR_USER_ID = "qc-01"
QUALITY_INSPECTOR_2_USER_ID = "qc-02"
COMPLIANCE_OFFICER_USER_ID = "compliance-01"
COMPLIANCE_OFFICER_2_USER_ID = "compliance-02"
DUAL_ROLE_USER_ID = "dual-01"

TEST_USERS = {
    "sales_engineer_headers": build_user_headers(
        SALES_ENGINEER_USER_ID, "SalesEngineer"
    ),
    "contracts_admin_headers": build_user_headers(
        CONTRACTS_ADMIN_USER_ID, "ContractsAdmin"
    ),
    "contracts_admin_2_headers": build_user_headers(
        CONTRACTS_ADMIN_2_USER_ID, "ContractsAdmin"
    ),
    "plant_scheduler_headers": build_user_headers(
        PLANT_SCHEDULER_USER_ID, "PlantScheduler"
    ),
    "quality_inspector_headers": build_user_headers(
        QUALITY_INSPECTOR_USER_ID, "QualityInspector"
    ),
    "quality_inspector_2_headers": build_user_headers(
        QUALITY_INSPECTOR_2_USER_ID, "QualityInspector"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_2_headers": build_user_headers(
        COMPLIANCE_OFFICER_2_USER_ID, "ComplianceOfficer"
    ),
    # Fallback only, for calls that are not ownership-gated (bad payloads,
    # unknown resources, and shared read endpoints).
    "dealer_agent_headers": build_user_headers("dealer-agent-unbound", "DealerAgent"),
}


def make_sales_engineer_headers(user_id: str) -> dict:
    """SalesEngineer headers under a caller-chosen identity (opaque role)."""
    return build_user_headers(user_id, "SalesEngineer")


def make_contracts_admin_headers(user_id: str) -> dict:
    """ContractsAdmin headers under a caller-chosen identity (opaque role)."""
    return build_user_headers(user_id, "ContractsAdmin")


def make_plant_scheduler_headers(user_id: str) -> dict:
    """PlantScheduler headers under a caller-chosen identity (opaque role)."""
    return build_user_headers(user_id, "PlantScheduler")


def make_quality_inspector_headers(user_id: str) -> dict:
    """QualityInspector headers under a caller-chosen identity (opaque role)."""
    return build_user_headers(user_id, "QualityInspector")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers under a caller-chosen identity (opaque role)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_dealer_agent_headers(dealer_id: str) -> dict:
    """DealerAgent headers. X-User-ID must be the acting dealer's own id, so
    every ownership-gated dealer call must pass the real Dealer id here."""
    return build_user_headers(dealer_id, "DealerAgent")


def headers_without_role(user_id: str) -> dict:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> dict:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str, role: str) -> dict:
    """Headers naming a role the PRD does not declare."""
    return build_user_headers(user_id, role)
