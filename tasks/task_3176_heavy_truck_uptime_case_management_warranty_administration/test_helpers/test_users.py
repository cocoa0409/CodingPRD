"""Pre-built role headers for every role in the PRD (Section 2.1).

FleetManager and DealerAdvisor are entity-backed: their X-User-ID must be the
id of an existing Fleet / Dealer respectively. Always build their headers with
make_fleet_manager_headers(fleet_id) / make_dealer_advisor_headers(dealer_id)
after creating the entity — the shared constants below exist only for tests
that do not exercise ownership (e.g. 400/403 checks before any entity exists).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not
# exercise entity-backed ownership checks.
TEST_USERS = {
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "uptime_coordinator_headers": build_user_headers("test-uptime-coord-1", "UptimeCoordinator"),
    "dealer_advisor_headers": build_user_headers("test-dealer-advisor-1", "DealerAdvisor"),
    "parts_manager_headers": build_user_headers("test-parts-manager-1", "PartsManager"),
    "warranty_admin_headers": build_user_headers("test-warranty-admin-1", "WarrantyAdmin"),
    "supplier_manager_headers": build_user_headers("test-supplier-manager-1", "SupplierManager"),
}


def make_fleet_manager_headers(fleet_id: str) -> dict:
    """FleetManager is entity_backed:Fleet. Pass the actual Fleet.id whenever
    the call is ownership-gated (fleet-scoped writes)."""
    return build_user_headers(fleet_id, "FleetManager")


def make_dealer_advisor_headers(dealer_id: str) -> dict:
    """DealerAdvisor is entity_backed:Dealer. Pass the actual Dealer.id whenever
    the call is ownership-gated (dealer-scoped writes)."""
    return build_user_headers(dealer_id, "DealerAdvisor")


def make_uptime_coordinator_headers(user_id: str = "test-uptime-coord-1") -> dict:
    return build_user_headers(user_id, "UptimeCoordinator")


def make_parts_manager_headers(user_id: str = "test-parts-manager-1") -> dict:
    return build_user_headers(user_id, "PartsManager")


def make_warranty_admin_headers(user_id: str = "test-warranty-admin-1") -> dict:
    return build_user_headers(user_id, "WarrantyAdmin")


def make_supplier_manager_headers(user_id: str = "test-supplier-manager-1") -> dict:
    return build_user_headers(user_id, "SupplierManager")
