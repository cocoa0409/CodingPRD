"""Role headers for the six PRD §2.1 roles.

The five operator roles are identity-opaque per PRD §2.1 ("an opaque operator
identifier not tied to any persisted entity"), so shared constants are canonical.

The Customer role is entity-backed: PRD §2.1 requires that when X-User-Role is
Customer, X-User-ID is the id of the acting Customer entity. Never reuse one
constant across distinct customers — a PRD-faithful server rejects it with
ERR_UNAUTHORIZED. Always call make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "supply_planner_headers": build_user_headers("test-supply-planner-1", "SupplyPlanner"),
    "channel_manager_headers": build_user_headers("test-channel-manager-1", "ChannelManager"),
    "quality_engineer_headers": build_user_headers(
        "test-quality-engineer-1", "QualityEngineer"
    ),
    "field_engineer_headers": build_user_headers("test-field-engineer-1", "FieldEngineer"),
}

# No headers at all — for the unauthenticated-request probe.
NO_AUTH_HEADERS: dict = {}


def make_customer_headers(customer_id: str) -> dict:
    """Customer role is entity_backed:Customer — pass the real Customer.id."""
    return build_user_headers(customer_id, "Customer")
