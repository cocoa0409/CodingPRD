"""Pre-built role headers for every role in the PRD (§2.1).

CustomerAdmin is entity-backed: X-User-ID must equal the acting Customer.id
whenever the call is ownership-gated — use make_customer_admin_headers with the
real customer id for those calls. All other roles are opaque operator
identifiers, so their shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form (PRD §2.1).
    "plant_manager_headers": build_user_headers("test-plant-manager-1", "PlantManager"),
    "contracts_officer_headers": build_user_headers(
        "test-contracts-officer-1", "ContractsOfficer"
    ),
    "supply_chain_auditor_headers": build_user_headers(
        "test-supply-chain-auditor-1", "SupplyChainAuditor"
    ),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    "logistics_coordinator_headers": build_user_headers(
        "test-logistics-coordinator-1", "LogisticsCoordinator"
    ),
    "warranty_administrator_headers": build_user_headers(
        "test-warranty-administrator-1", "WarrantyAdministrator"
    ),
    "recycling_coordinator_headers": build_user_headers(
        "test-recycling-coordinator-1", "RecyclingCoordinator"
    ),
    # entity_backed:Customer — fallback for non-ownership calls only.
    "customer_admin_headers": build_user_headers("test-customer-admin-1", "CustomerAdmin"),
}


def make_customer_admin_headers(user_id: str) -> dict:
    """CustomerAdmin is entity-backed by Customer: pass the actual Customer.id
    as user_id whenever the call is ownership-gated (reservations, deliveries,
    warranty claims, recycling obligations)."""
    return build_user_headers(user_id, "CustomerAdmin")
