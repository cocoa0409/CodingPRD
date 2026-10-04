"""Pre-built role headers for the seven declared roles (PRD §2.1).

Two roles are entity-backed: SupplierManager acts with X-User-ID == Supplier.id,
Customer acts with X-User-ID == Customer.id (the aircraft's customer_id on
customer-scoped writes). For those, the shared constants below are fallbacks
for non-ownership tests only; ownership-gated calls MUST use the per-instance
builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form (PRD §2.1).
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "line_manager_headers": build_user_headers("test-line-manager-1", "LineManager"),
    "delivery_manager_headers": build_user_headers("test-delivery-manager-1", "DeliveryManager"),
    # QualityInspector is opaque, but its X-User-ID is recorded as
    # reported_by_id / dispositioned_by_id (PRD §2.1, §3.6), so segregation
    # tests need two stable distinct ids.
    "quality_inspector_headers": build_user_headers("insp-1", "QualityInspector"),
    "quality_inspector_2_headers": build_user_headers("insp-2", "QualityInspector"),
    # Entity-backed roles: fallback constants for non-ownership tests ONLY.
    "supplier_manager_headers": build_user_headers("test-supplier-manager-1", "SupplierManager"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_supplier_manager_headers(supplier_id: str) -> dict:
    """SupplierManager is entity-backed (PRD §2.1): X-User-ID must equal the
    acting Supplier's id on every supplier-scoped write."""
    return build_user_headers(supplier_id, "SupplierManager")


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed (PRD §2.1): X-User-ID must equal the aircraft's
    customer_id on the walkthrough, delivery acceptance, and customer-side
    negotiation calls."""
    return build_user_headers(customer_id, "Customer")


def make_quality_inspector_headers(user_id: str) -> dict:
    """QualityInspector is opaque, but disposition must be segregated from
    reporting (PRD §3.6): pass a distinct user_id from the reporter's."""
    return build_user_headers(user_id, "QualityInspector")
