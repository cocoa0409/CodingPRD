"""Pre-built role headers for every role in the PRD.

ListingAgent and Vendor are entity-backed roles: when a call is
ownership-gated, the caller's X-User-ID must equal the acting entity's id,
so fixtures use the per-instance builders below. The shared constants are
safe only for opaque roles or for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "program_underwriter_headers": build_user_headers("test-program-underwriter-1", "ProgramUnderwriter"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "listing_agent_headers": build_user_headers("test-listing-agent-1", "ListingAgent"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_listing_agent_headers(user_id: str) -> dict:
    """ListingAgent is entity-backed by Agent: pass the acting Agent's id."""
    return build_user_headers(user_id, "ListingAgent")


def make_vendor_headers(user_id: str) -> dict:
    """Vendor is entity-backed by Vendor: pass the acting Vendor's id."""
    return build_user_headers(user_id, "Vendor")
