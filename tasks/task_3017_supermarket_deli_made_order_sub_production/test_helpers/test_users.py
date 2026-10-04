"""Pre-built role headers for every role the contract recognizes.

PlatformAdmin and ScaleOperator are opaque: their X-User-ID is an operator
identifier that is never compared to any entity id. DeliManager, DeliClerk and
BakeryCoordinator are entity-backed: X-User-ID must name an acting Associate row
and every ownership, certification, allergy and segregation check reads that row.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles and for calls whose success does
# not depend on the caller being a specific entity.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "scale_operator_headers": build_user_headers("test-scale-operator-1", "ScaleOperator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership calls only.
    "deli_manager_headers": build_user_headers("test-deli-manager-1", "DeliManager"),
    "deli_clerk_headers": build_user_headers("test-deli-clerk-1", "DeliClerk"),
    "bakery_coordinator_headers": build_user_headers("test-bakery-coordinator-1", "BakeryCoordinator"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """PlatformAdmin is opaque; the identifier is an operator handle."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_scale_operator_headers(user_id: str = "test-scale-operator-1") -> dict:
    """ScaleOperator is opaque; the identifier is an operator handle."""
    return build_user_headers(user_id, "ScaleOperator")


def make_deli_manager_headers(user_id: str) -> dict:
    """For DeliManager (entity_backed:Associate). Pass the acting Associate.id
    whenever the call is ownership-, certification- or segregation-gated."""
    return build_user_headers(user_id, "DeliManager")


def make_deli_clerk_headers(user_id: str) -> dict:
    """For DeliClerk (entity_backed:Associate). Pass the acting Associate.id
    whenever the call is ownership-, certification-, allergy- or segregation-gated."""
    return build_user_headers(user_id, "DeliClerk")


def make_bakery_coordinator_headers(user_id: str) -> dict:
    """For BakeryCoordinator (entity_backed:Associate). Pass the acting Associate.id."""
    return build_user_headers(user_id, "BakeryCoordinator")