"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Entity-backed roles (Developer, Merchant) MUST use the per-instance
# builders below whenever the call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "reviewer_headers": build_user_headers("rev-1", "Reviewer"),
    # Fallbacks only: do NOT use these for ownership-gated calls.
    "developer_headers": build_user_headers("test-dev-1", "Developer"),
    "merchant_headers": build_user_headers("test-merchant-1", "Merchant"),
}


def make_developer_headers(user_id: str) -> dict:
    """Headers for role Developer (entity_backed:DeveloperAccount).

    Pass the actual DeveloperAccount.id as user_id whenever the call is
    ownership-gated (own apps, own tickets, own data-deletion confirmations).
    """
    return build_user_headers(user_id, "Developer")


def make_merchant_headers(user_id: str) -> dict:
    """Headers for role Merchant (entity_backed:MerchantAccount).

    Pass the actual MerchantAccount.id as user_id whenever the call is
    ownership-gated (own installations, invoices, charges, tickets).
    """
    return build_user_headers(user_id, "Merchant")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """Headers for role PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_reviewer_headers(user_id: str = "rev-1") -> dict:
    """Headers for role Reviewer (opaque identity)."""
    return build_user_headers(user_id, "Reviewer")
