"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "policy_reviewer_headers": build_user_headers("reviewer-1", "PolicyReviewer"),
    "billing_admin_headers": build_user_headers("billing-1", "BillingAdmin"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "advertiser_headers": build_user_headers("advertiser-fallback-1", "Advertiser"),
}


def make_advertiser_headers(user_id: str) -> dict:
    """For the Advertiser role (entity-backed: AdvertiserAccount). Pass the actual
    AdvertiserAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Advertiser")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_policy_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    return build_user_headers(user_id, "PolicyReviewer")


def make_billing_admin_headers(user_id: str = "billing-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")


def make_anonymous_headers(user_id: str = "anon-caller-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
