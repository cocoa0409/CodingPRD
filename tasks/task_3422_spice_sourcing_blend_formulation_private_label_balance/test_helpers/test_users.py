"""Pre-built role headers for every role in the PRD (§2.1 role catalog).

Opaque roles (everyone except SupplierRep) use shared constants: their
X-User-ID is never compared to an entity id except where a business rule
explicitly references it (PRD §2.1) — for those cases use the per-id builders.

SupplierRep is entity-backed: X-User-ID MUST be the acting Supplier's id
(PRD §2.1), so always build its headers with make_supplier_rep_headers(supplier_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "supply_planner_headers": build_user_headers("sp-1", "SupplyPlanner"),
    "quality_analyst_headers": build_user_headers("qa-1", "QualityAnalyst"),
    "quality_manager_headers": build_user_headers("qm-1", "QualityManager"),
    "flavor_scientist_headers": build_user_headers("fs-1", "FlavorScientist"),
    "production_scheduler_headers": build_user_headers("ps-1", "ProductionScheduler"),
    "recall_coordinator_headers": build_user_headers("rc-1", "RecallCoordinator"),
    # Fallback only for SupplierRep calls that are NOT ownership-gated.
    "supplier_rep_headers": build_user_headers("sr-1", "SupplierRep"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_supply_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyPlanner")


def make_quality_analyst_headers(user_id: str) -> dict:
    """For QualityAnalyst callers whose identity matters (segregation of duties)."""
    return build_user_headers(user_id, "QualityAnalyst")


def make_quality_manager_headers(user_id: str) -> dict:
    """For QualityManager callers whose identity matters (segregation of duties)."""
    return build_user_headers(user_id, "QualityManager")


def make_supplier_rep_headers(supplier_id: str) -> dict:
    """SupplierRep is entity-backed: pass the actual Supplier.id whenever the
    call is ownership-gated (lot reads are restricted to supplier_id == X-User-ID)."""
    return build_user_headers(supplier_id, "SupplierRep")
