"""Pre-built role headers for the six roles in PRD §2.1.

Identity semantics (PRD §2.1):
- LicenseeManager: X-User-ID IS the acting Licensee's id (entity-backed).
- WholesaleBuyer:  X-User-ID IS the acting RetailAccount's id (entity-backed).
- The other four roles carry an opaque operator id never compared to entities.

The shared TEST_USERS entries for the two entity-backed roles are fallbacks for
tests that do NOT exercise ownership (e.g. plain reads). Any ownership-gated
call MUST use make_licensee_manager_headers(licensee["id"]) /
make_wholesale_buyer_headers(account["id"]) with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "production_planner_headers": build_user_headers("test-production-planner-1", "ProductionPlanner"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-coordinator-1", "LogisticsCoordinator"),
    "warranty_admin_headers": build_user_headers("test-warranty-admin-1", "WarrantyAdmin"),
    # Entity-backed roles — fallback for non-ownership reads only.
    "licensee_manager_headers": build_user_headers("test-licensee-manager-1", "LicenseeManager"),
    "wholesale_buyer_headers": build_user_headers("test-wholesale-buyer-1", "WholesaleBuyer"),
}


def make_licensee_manager_headers(user_id: str) -> dict:
    """LicenseeManager is entity-backed: pass the acting Licensee's id whenever
    the call is ownership-gated (order create/submit/cancel, appointment
    create/cancel, claim create, claim info-response)."""
    return build_user_headers(user_id, "LicenseeManager")


def make_wholesale_buyer_headers(user_id: str) -> dict:
    """WholesaleBuyer is entity-backed: pass the acting RetailAccount's id
    whenever the call is ownership-gated (order create/submit/cancel)."""
    return build_user_headers(user_id, "WholesaleBuyer")
