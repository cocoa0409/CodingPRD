"""Pre-built role headers for every role in the PRD.

All eight roles are opaque (PRD section 2.1): X-User-ID is not tied to any
persisted entity and no ownership check compares it to a resource id. The one
place identity matters is write-down segregation of duties (PRD section 3.8):
the deciding FinanceController's X-User-ID must differ from the write-down's
proposed_by_user_id. Use make_finance_controller_headers(<proposer_id>) to
construct the forbidden pairing, or a different id for the legal one.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants — canonical identities for calls that are not
# segregation-sensitive. Distinct stable ids per role so a proposer id never
# collides with the shared decider id by accident.
TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        "test-platform-admin-1", UserRole.PLATFORM_ADMIN.value
    ),
    "procurement_manager_headers": build_user_headers(
        "test-procurement-1", UserRole.PROCUREMENT_MANAGER.value
    ),
    "quality_manager_headers": build_user_headers(
        "test-quality-1", UserRole.QUALITY_MANAGER.value
    ),
    "plant_manager_headers": build_user_headers(
        "test-plant-1", UserRole.PLANT_MANAGER.value
    ),
    "product_manager_headers": build_user_headers(
        "test-product-1", UserRole.PRODUCT_MANAGER.value
    ),
    "channel_manager_headers": build_user_headers(
        "test-channel-1", UserRole.CHANNEL_MANAGER.value
    ),
    "demand_planner_headers": build_user_headers(
        "planner-1", UserRole.DEMAND_PLANNER.value
    ),
    "finance_controller_headers": build_user_headers(
        "fin-1", UserRole.FINANCE_CONTROLLER.value
    ),
}

# A second planner identity, for tests needing two distinct planners.
PLANNER_ALT_HEADERS = build_user_headers(
    "planner-2", UserRole.DEMAND_PLANNER.value
)


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_procurement_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PROCUREMENT_MANAGER.value)


def make_quality_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.QUALITY_MANAGER.value)


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PLANT_MANAGER.value)


def make_product_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PRODUCT_MANAGER.value)


def make_channel_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.CHANNEL_MANAGER.value)


def make_demand_planner_headers(user_id: str) -> dict:
    """DemandPlanner with a caller-chosen identity; the id lands on
    proposed_by_user_id when this user proposes a write-down."""
    return build_user_headers(user_id, UserRole.DEMAND_PLANNER.value)


def make_finance_controller_headers(user_id: str) -> dict:
    """FinanceController with a caller-chosen identity. Passing the write-down
    proposer's id here constructs the forbidden self-decision; any other id
    satisfies segregation of duties."""
    return build_user_headers(user_id, UserRole.FINANCE_CONTROLLER.value)
