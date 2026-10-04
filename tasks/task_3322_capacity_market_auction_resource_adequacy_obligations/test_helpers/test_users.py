"""Pre-built role headers for every role in the PRD (§2.1).

MarketAdmin and SettlementOps are opaque roles (X-User-ID not tied to any
persisted entity), so shared constants are their canonical form.

ResourceOwner is entity-backed: X-User-ID must equal the id of the acting
ResourceOwnerEntity. Fixtures MUST use make_resource_owner_headers(owner_id)
for ownership-gated calls; the shared constant is only for tests that do not
exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical shared form.
    "market_admin_headers": build_user_headers("test-market-admin-1", "MarketAdmin"),
    "settlement_ops_headers": build_user_headers("test-settlement-ops-1", "SettlementOps"),
    # Entity-backed role: fallback for non-ownership tests only.
    "resource_owner_headers": build_user_headers("test-resource-owner-1", "ResourceOwner"),
}


def make_resource_owner_headers(owner_id: str) -> dict:
    """ResourceOwner headers for the specific ResourceOwnerEntity `owner_id`.

    Mandatory for every ownership-gated call (resource create/retire,
    accreditations, offers, withdrawals, replacements, measurement reports).
    """
    return build_user_headers(owner_id, "ResourceOwner")
