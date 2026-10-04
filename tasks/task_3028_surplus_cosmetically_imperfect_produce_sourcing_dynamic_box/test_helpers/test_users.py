"""Pre-built role headers for every role in the PRD's RBAC model.

Three of the four roles are entity-backed: a `Customer` header carries the
acting `Customer.id`, a `Supplier` header the acting `Supplier.id`, and a
`FulfillmentOperator` header the acting `FulfillmentCenter.id`. The
per-instance builders below are what ownership-gated calls must use; the
shared constants are only safe for opaque roles or for calls whose outcome
does not depend on ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Customer — shared constant is a non-owning fallback only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # entity_backed:Supplier — shared constant is a non-owning fallback only.
    "supplier_headers": build_user_headers("test-supplier-1", "Supplier"),
    # entity_backed:FulfillmentCenter — shared constant is a non-owning fallback only.
    "operator_headers": build_user_headers("test-center-1", "FulfillmentOperator"),
    # opaque — the canonical form for the administrator role.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id when
    the call is ownership-gated (finalize, file a claim, skip/pause/resume/cancel)."""
    return build_user_headers(user_id, "Customer")


def make_supplier_headers(user_id: str) -> dict:
    """For Supplier (entity_backed:Supplier). Pass the actual Supplier.id when
    the call is ownership-gated (place a bid, withdraw a bid, list a lot)."""
    return build_user_headers(user_id, "Supplier")


def make_operator_headers(user_id: str) -> dict:
    """For FulfillmentOperator (entity_backed:FulfillmentCenter). Pass the actual
    FulfillmentCenter.id when the call is ownership-gated (build, pack)."""
    return build_user_headers(user_id, "FulfillmentOperator")


def unauth_headers() -> dict:
    """No role header at all — trips the priority 1 authentication rung."""
    return {"Content-Type": "application/json"}