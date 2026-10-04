"""Pre-built role headers for every role the PRD declares.

Entity-backed roles (SourceOperator -> DataSource, ShopOperator -> Shop,
VehicleOwner -> ConsumerAccount, DealerAgent -> Dealer) must be built with the
acting entity's real ``id`` whenever a call is ownership- or identity-gated.
The shared constants are only safe for opaque roles or for calls whose success
does not depend on identity.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "network_admin_headers": build_user_headers("test-network-admin-1", "NetworkAdmin"),
    "guarantee_admin_headers": build_user_headers("test-guarantee-admin-1", "GuaranteeAdmin"),
    # Shared fallbacks for entity-backed roles — non-ownership tests only.
    "source_operator_headers": build_user_headers("test-source-operator-1", "SourceOperator"),
    "shop_operator_headers": build_user_headers("test-shop-operator-1", "ShopOperator"),
    "vehicle_owner_headers": build_user_headers("test-vehicle-owner-1", "VehicleOwner"),
    "dealer_agent_headers": build_user_headers("test-dealer-agent-1", "DealerAgent"),
}

ANY_READER_HEADERS = TEST_USERS["network_admin_headers"]


def make_source_operator_headers(source_id: str) -> dict:
    """SourceOperator identity is the DataSource's id (record submission and
    correction verification both compare against it)."""
    return build_user_headers(source_id, "SourceOperator")


def make_shop_operator_headers(shop_id: str) -> dict:
    """ShopOperator identity is the Shop's id."""
    return build_user_headers(shop_id, "ShopOperator")


def make_vehicle_owner_headers(consumer_id: str) -> dict:
    """VehicleOwner identity is the ConsumerAccount's id."""
    return build_user_headers(consumer_id, "VehicleOwner")


def make_dealer_agent_headers(dealer_id: str) -> dict:
    """DealerAgent identity is the Dealer's id; ownership checks on listings and
    dealer-scoped purchases compare against it."""
    return build_user_headers(dealer_id, "DealerAgent")


def make_network_admin_headers() -> dict:
    return TEST_USERS["network_admin_headers"]


def make_guarantee_admin_headers() -> dict:
    return TEST_USERS["guarantee_admin_headers"]
