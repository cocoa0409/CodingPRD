"""Pre-built role headers for every role in the PRD (§2.1).

Five roles carry an opaque operator identity; the ``Customer`` role is
entity-backed, so ownership-gated calls must use ``make_customer_headers``
with the acting customer's own ``id``.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plain_headers": {"Content-Type": "application/json"},
    "chain_admin_headers": build_user_headers("test-chain-admin-1", "ChainAdmin"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "credit_analyst_headers": build_user_headers("test-credit-analyst-1", "CreditAnalyst"),
    "sales_associate_headers": build_user_headers("test-sales-associate-1", "SalesAssociate"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    # entity_backed role: this constant is a fallback for reads that are not
    # ownership-gated. Ownership-gated calls must use make_customer_headers().
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "bad_role_headers": build_user_headers("test-unknown-1", "NotARole"),
}


def make_customer_headers(user_id: str) -> dict:
    """Headers for the Customer role, bound to the acting customer's own id.

    The Customer role is entity-backed, so any ownership-gated call
    (accepting a countered offer, declining it, requesting a CAD revision,
    approving CAD, cancelling a commission, reading own statements) must
    carry the real Customer.id as X-User-ID.
    """
    return build_user_headers(user_id, "Customer")


__all__ = ["TEST_USERS", "make_customer_headers"]