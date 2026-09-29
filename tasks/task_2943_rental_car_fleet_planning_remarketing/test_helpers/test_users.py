"""Actor identities and header builders.

Four of the five roles carry an opaque operator identifier. `MarketOperator`
is the exception: the PRD scopes a branch operator to one market and compares
the acting identifier against a market row, so a market operator's
`X-User-ID` is the identifier of the `Market` it acts for. That is why the
market-operator builder takes a market id rather than a canned string.

Every distinct actor below owns a distinct identifier, because several PRD
controls are split across two people and compare the two identifiers for
inequality.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --------------------------------------------------------------------------
# Opaque operator identifiers, one per distinct actor.
# --------------------------------------------------------------------------

PLATFORM_ADMIN_ID = "u-admin-1"
FLEET_PLANNER_ID = "u-plan-1"
FLEET_PLANNER_ALT_ID = "u-plan-2"
FLEET_CONTROLLER_A_ID = "u-ctl-a"
FLEET_CONTROLLER_B_ID = "u-ctl-b"
FLEET_CONTROLLER_C_ID = "u-ctl-c"
REMARKETING_MANAGER_A_ID = "u-rmk-a"
REMARKETING_MANAGER_B_ID = "u-rmk-b"
UNKNOWN_OPERATOR_ID = "u-nobody"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"user_id": PLATFORM_ADMIN_ID, "role": Role.PLATFORM_ADMIN},
    "fleet_planner": {"user_id": FLEET_PLANNER_ID, "role": Role.FLEET_PLANNER},
    "fleet_planner_alt": {"user_id": FLEET_PLANNER_ALT_ID, "role": Role.FLEET_PLANNER},
    "fleet_controller_a": {"user_id": FLEET_CONTROLLER_A_ID, "role": Role.FLEET_CONTROLLER},
    "fleet_controller_b": {"user_id": FLEET_CONTROLLER_B_ID, "role": Role.FLEET_CONTROLLER},
    "fleet_controller_c": {"user_id": FLEET_CONTROLLER_C_ID, "role": Role.FLEET_CONTROLLER},
    "remarketing_manager_a": {
        "user_id": REMARKETING_MANAGER_A_ID,
        "role": Role.REMARKETING_MANAGER,
    },
    "remarketing_manager_b": {
        "user_id": REMARKETING_MANAGER_B_ID,
        "role": Role.REMARKETING_MANAGER,
    },
}


# --------------------------------------------------------------------------
# Header builders
# --------------------------------------------------------------------------


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_fleet_planner_headers(user_id: str = FLEET_PLANNER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.FLEET_PLANNER)


def make_fleet_controller_headers(user_id: str = FLEET_CONTROLLER_A_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.FLEET_CONTROLLER)


def make_remarketing_manager_headers(
    user_id: str = REMARKETING_MANAGER_A_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.REMARKETING_MANAGER)


def make_market_operator_headers(market_id: str) -> Dict[str, str]:
    """A branch operator acts as the market it belongs to."""
    return build_user_headers(market_id, Role.MARKET_OPERATOR)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Explicit role/identifier pair, for the access-control matrices."""
    return build_user_headers(user_id, role)


def make_blank_role_headers(user_id: str = FLEET_PLANNER_ID) -> Dict[str, str]:
    """Genuinely empty role value, never a whitespace-filled one."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def make_blank_user_headers(role: str = Role.FLEET_PLANNER) -> Dict[str, str]:
    """Genuinely empty identifier value, never a whitespace-filled one."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def make_unrecognised_role_headers(
    role: str = "FleetOverlord", user_id: str = UNKNOWN_OPERATOR_ID
) -> Dict[str, str]:
    """A syntactically present but unrecognized role name."""
    return build_user_headers(user_id, role)
