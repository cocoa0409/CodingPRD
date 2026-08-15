"""Pre-built role headers for every role in the PRD (§2.1).

DistributorAdmin, SalesRep, WarehouseOps, QualityInspector and SupplierAdmin are
opaque identities: X-User-ID is not compared to any entity's id. CustomerBuyer
is entity-backed by Customer: X-User-ID must equal the acting Customer's id
whenever the call is ownership-gated, so ownership-gated calls MUST use
make_customer_buyer_headers(customer["id"]) and never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "distributor_admin_headers": build_user_headers("admin-01", "DistributorAdmin"),
    "sales_rep_headers": build_user_headers("sales-01", "SalesRep"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_buyer_headers": build_user_headers("buyer-01", "CustomerBuyer"),
    "warehouse_ops_headers": build_user_headers("wh-01", "WarehouseOps"),
    "quality_inspector_headers": build_user_headers("qi-01", "QualityInspector"),
    "supplier_admin_headers": build_user_headers("sup-01", "SupplierAdmin"),
}


def make_distributor_admin_headers(user_id: str = "admin-01") -> dict:
    return build_user_headers(user_id, "DistributorAdmin")


def make_sales_rep_headers(user_id: str = "sales-01") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_customer_buyer_headers(customer_id: str) -> dict:
    """For CustomerBuyer (entity_backed:Customer). Pass the acting Customer.id
    whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "CustomerBuyer")


def make_warehouse_ops_headers(user_id: str = "wh-01") -> dict:
    return build_user_headers(user_id, "WarehouseOps")


def make_quality_inspector_headers(user_id: str = "qi-01") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_supplier_admin_headers(user_id: str = "sup-01") -> dict:
    return build_user_headers(user_id, "SupplierAdmin")
