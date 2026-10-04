"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The staff and Anonymous roles are opaque (their X-User-ID
# is an operator string never compared to a resource id). Customer is
# entity-backed: use make_customer_headers(account_id) for ownership-gated
# calls; the shared constant is safe only for tests that do not exercise
# ownership (e.g. forbidden-role probes).
TEST_USERS = {
    "regional_admin_headers": build_user_headers("op-regional-admin-1", "RegionalAdmin"),
    "store_manager_headers": build_user_headers("op-store-manager-1", "StoreManager"),
    "store_associate_headers": build_user_headers("op-store-associate-1", "StoreAssociate"),
    "customer_headers": build_user_headers("customer-placeholder", "Customer"),
    "anonymous_headers": build_user_headers("anonymous-1", "Anonymous"),
}


def make_regional_admin_headers(user_id: str = "op-regional-admin-1") -> dict:
    return build_user_headers(user_id, "RegionalAdmin")


def make_store_manager_headers(user_id: str = "op-store-manager-1") -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_store_associate_headers(user_id: str = "op-store-associate-1") -> dict:
    return build_user_headers(user_id, "StoreAssociate")


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the acting LoyaltyAccount's id whenever
    the call is ownership-gated (order create/cancel, claims, pickups,
    bookings, own-account reads)."""
    return build_user_headers(user_id, "Customer")


def make_anonymous_headers(user_id: str = "anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
