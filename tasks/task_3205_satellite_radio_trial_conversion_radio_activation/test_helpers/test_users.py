"""Role headers. Entity-backed roles get per-instance builders; opaque roles
have shared constants (their X-User-ID is never compared to an entity id)."""

from prd_bench_local_runner.testing import build_user_headers


PLATFORM_ADMIN_HEADERS = build_user_headers("operator-admin-1", "PlatformAdmin")
RETENTION_AGENT_HEADERS = build_user_headers("operator-retention-1", "RetentionAgent")
SYSTEM_OPERATOR_HEADERS = build_user_headers("operator-sysop-1", "SystemOperator")

# Anonymous registration requires no identity headers at all.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}

TEST_USERS = {
    "platform_admin_headers": PLATFORM_ADMIN_HEADERS,
    "retention_agent_headers": RETENTION_AGENT_HEADERS,
    "system_operator_headers": SYSTEM_OPERATOR_HEADERS,
    "anonymous_headers": ANONYMOUS_HEADERS,
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed: X-User-ID must equal the Customer.id for
    ownership-gated calls to pass."""
    return build_user_headers(customer_id, "Customer")


def make_automaker_headers(automaker_id: str) -> dict:
    """AutomakerPartner is entity-backed: X-User-ID is the Automaker.id."""
    return build_user_headers(automaker_id, "AutomakerPartner")


def make_dealer_headers(dealer_id: str) -> dict:
    """DealerPartner is entity-backed: X-User-ID is the Dealer.id."""
    return build_user_headers(dealer_id, "DealerPartner")
