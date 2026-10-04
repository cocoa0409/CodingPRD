"""Pre-built role headers for every role in the PRD.

Entity-backed roles (Developer, User) require their X-User-ID to equal the
acting entity's id; the shared constants are safe only for calls that never
exercise an ownership check. Fixtures must call make_developer_headers /
make_user_headers with the real entity id for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "platform_ops_headers": build_user_headers("ops-1", "PlatformOps"),
    "store_reviewer_headers": build_user_headers("reviewer-1", "StoreReviewer"),
    "trust_safety_headers": build_user_headers("trust-1", "TrustSafety"),
    # Entity-backed roles — fallback constants for NON-ownership tests only.
    "developer_headers": build_user_headers("test-developer-1", "Developer"),
    "user_headers": build_user_headers("test-user-1", "User"),
}


def make_developer_headers(developer_account_id: str) -> dict:
    """Headers for the Developer role. Pass the actual DeveloperAccount.id
    whenever the call is ownership-gated (title writes, overrides, batches)."""
    return build_user_headers(developer_account_id, "Developer")


def make_user_headers(user_account_id: str) -> dict:
    """Headers for the User role. Pass the actual UserAccount.id whenever the
    call is ownership-gated (purchases, refunds, reviews, redemptions)."""
    return build_user_headers(user_account_id, "User")
