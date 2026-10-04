"""Pre-built role headers for every role in the PRD.

Customer and SupplierRep are identity-backed roles: their X-User-ID must be
the id of the Customer / Supplier record being acted on, so fixtures and
tests that exercise ownership-gated calls MUST use the per-instance builders
below. The shared constants in TEST_USERS are safe only for opaque roles and
for tests whose outcome does not depend on identity matching.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "network_admin_headers": build_user_headers("test-netadmin-1", "NetworkAdmin"),
    "hub_operator_headers": build_user_headers("test-hubop-1", "HubOperator"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "carrier_rep_headers": build_user_headers("test-carrier-1", "CarrierRep"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "supplier_rep_headers": build_user_headers("test-supplierrep-1", "SupplierRep"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (identity-backed by the Customer record). Pass the actual
    Customer.id whenever the call is ownership-gated (placing/cancelling the
    customer's own orders, opening claims, requesting returns)."""
    return build_user_headers(user_id, "Customer")


def make_supplier_rep_headers(user_id: str) -> dict:
    """For SupplierRep (identity-backed by the Supplier record). Pass the
    actual Supplier.id whenever the call is ownership-gated (disputing the
    supplier's own chargeback, drop-ship ship/deliver confirms)."""
    return build_user_headers(user_id, "SupplierRep")
