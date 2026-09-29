"""Pre-built request headers for every role in the PRD (§2.1).

`PlatformAdmin`, `Broker` and `EscrowAgent` carry opaque operator identifiers that
the server never compares to an entity `id`, so shared constants are the canonical
form for them. Several rules do compare one operator identifier against another
(segregation of duties), so this module also publishes distinct named operators.

`Seller` and `Buyer` carry the `id` of the acting record, so ownership-gated calls
MUST use `make_seller_headers(seller["id"])` / `make_buyer_headers(buyer["id"])`.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Load-bearing operator identities. Segregation of duties compares these against
# one another, so a fixture and the test that consumes it must pick deliberately.
BROKER_VERIFIER_USER_ID = "broker-verify-1"
BROKER_DILIGENCE_USER_ID = "broker-diligence-1"
BROKER_OPS_USER_ID = "broker-ops-1"
BROKER_OPS_ALT_USER_ID = "broker-ops-2"
ESCROW_FUNDER_USER_ID = "escrow-agent-alpha"
ESCROW_RELEASER_USER_ID = "escrow-agent-beta"
PLATFORM_ADMIN_USER_ID = "platform-admin-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "broker_headers": build_user_headers(BROKER_OPS_USER_ID, "Broker"),
    "broker_verifier_headers": build_user_headers(BROKER_VERIFIER_USER_ID, "Broker"),
    "broker_diligence_headers": build_user_headers(BROKER_DILIGENCE_USER_ID, "Broker"),
    "broker_ops_alt_headers": build_user_headers(BROKER_OPS_ALT_USER_ID, "Broker"),
    "escrow_agent_headers": build_user_headers(ESCROW_FUNDER_USER_ID, "EscrowAgent"),
    "escrow_agent_alt_headers": build_user_headers(ESCROW_RELEASER_USER_ID, "EscrowAgent"),
    # Entity-backed roles — fallbacks for tests that never exercise ownership
    # (unauthenticated / unauthorized / malformed-body / unknown-identifier cases).
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_seller_headers(seller_id: str) -> Dict[str, str]:
    """Headers for the acting `Seller`; pass the real Seller.id (PRD §2.1)."""
    return build_user_headers(seller_id, "Seller")


def make_buyer_headers(buyer_id: str) -> Dict[str, str]:
    """Headers for the acting `Buyer`; pass the real Buyer.id (PRD §2.1)."""
    return build_user_headers(buyer_id, "Buyer")


def make_broker_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named `Broker` operator identity."""
    return build_user_headers(user_id, "Broker")


def make_escrow_agent_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named `EscrowAgent` operator identity."""
    return build_user_headers(user_id, "EscrowAgent")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a named `PlatformAdmin` operator identity."""
    return build_user_headers(user_id, "PlatformAdmin")


def headers_without_role(user_id: str = "anonymous-1") -> Dict[str, str]:
    """Headers that omit `X-User-Role` entirely (PRD §2.1 expects 401)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "anonymous-1") -> Dict[str, str]:
    """Headers naming a role outside the five recognised names (PRD §2.1 expects 401)."""
    return build_user_headers(user_id, "RouteInspector")


ALL_ROLE_HEADER_KEYS = [
    "platform_admin_headers",
    "broker_headers",
    "seller_headers",
    "buyer_headers",
    "escrow_agent_headers",
]
