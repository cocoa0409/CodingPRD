"""Caller identities and their request headers (PRD 2.1).

Six of the seven roles are opaque strings: the API only has to recognise the
role name, and `X-User-ID` for them is an arbitrary token that is stamped onto
audit fields. `Patron` is the exception -- its `X-User-ID` must be the id of a
real patron record, so patron headers are built per test from the enrolled
patron's id.

Where the specification requires two *different* officials (submitting a capital
project versus closing it), the tests must use distinct opaque ids; the pools
below exist so that no two such call sites accidentally share one.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque user ids, one family per role
# ---------------------------------------------------------------------------

SYSTEM_OPERATOR_ID = "ops-001"

# Surcharge fund controllers. Distinct ids matter for the duty separation rule.
FUND_CONTROLLER_ID = "sfc-001"
FUND_CONTROLLER_IDS = (
    "sfc-001",
    "sfc-002",
    "sfc-010",
    "sfc-020",
    "sfc-021",
    "sfc-030",
    "sfc-050",
    "sfc-701",
    "sfc-702",
    "sfc-703",
    "sfc-901",
    "sfc-902",
)

# Board officers who record decisions.
BOARD_OFFICER_ID = "mwr-001"
BOARD_OFFICER_IDS = (
    "mwr-001",
    "mwr-010",
    "mwr-030",
    "mwr-050",
    "mwr-702",
    "mwr-703",
    "mwr-901",
)

COMPLIANCE_OFFICER_ID = "cmp-001"
ASSORTMENT_PLANNER_ID = "asp-001"
STORE_CASHIER_ID = "csh-001"

# ---------------------------------------------------------------------------
# Ready-made header dictionaries for the six opaque roles
# ---------------------------------------------------------------------------

HEADERS_SYSTEM_OPERATOR = build_user_headers(
    SYSTEM_OPERATOR_ID, UserRole.SYSTEM_OPERATOR.value
)
HEADERS_FUND_CONTROLLER = build_user_headers(
    FUND_CONTROLLER_ID, UserRole.SURCHARGE_FUND_CONTROLLER.value
)
HEADERS_BOARD_OFFICER = build_user_headers(
    BOARD_OFFICER_ID, UserRole.MWR_BOARD_OFFICER.value
)
HEADERS_COMPLIANCE_OFFICER = build_user_headers(
    COMPLIANCE_OFFICER_ID, UserRole.COMPLIANCE_OFFICER.value
)
HEADERS_ASSORTMENT_PLANNER = build_user_headers(
    ASSORTMENT_PLANNER_ID, UserRole.ASSORTMENT_PLANNER.value
)
HEADERS_STORE_CASHIER = build_user_headers(
    STORE_CASHIER_ID, UserRole.STORE_CASHIER.value
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_operator": HEADERS_SYSTEM_OPERATOR,
    "fund_controller": HEADERS_FUND_CONTROLLER,
    "board_officer": HEADERS_BOARD_OFFICER,
    "compliance_officer": HEADERS_COMPLIANCE_OFFICER,
    "assortment_planner": HEADERS_ASSORTMENT_PLANNER,
    "store_cashier": HEADERS_STORE_CASHIER,
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_fund_controller_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named surcharge fund controller."""
    return build_user_headers(user_id, UserRole.SURCHARGE_FUND_CONTROLLER.value)


def make_board_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named MWR board officer."""
    return build_user_headers(user_id, UserRole.MWR_BOARD_OFFICER.value)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named compliance officer."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_cashier_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named store cashier."""
    return build_user_headers(user_id, UserRole.STORE_CASHIER.value)


def make_patron_headers(patron_id: str) -> Dict[str, str]:
    """Headers for a patron caller; the user id is that patron's own record id."""
    return build_user_headers(patron_id, UserRole.PATRON.value)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for any role/user-id pair."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Malformed / absent credentials (PRD 2.1)
# ---------------------------------------------------------------------------

# Both identifying headers omitted entirely.
HEADERS_NO_AUTH: Dict[str, str] = {"Content-Type": "application/json"}

# The role header present but empty. It is the empty string, never whitespace:
# a whitespace-only header value is rejected by the HTTP layer before the
# request is ever sent, which would test nothing about the API.
HEADERS_EMPTY_ROLE: Dict[str, str] = {
    "X-User-ID": STORE_CASHIER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

# A role header that is syntactically fine but names no known role.
HEADERS_UNKNOWN_ROLE: Dict[str, str] = build_user_headers(
    STORE_CASHIER_ID, "WarehouseForeman"
)

# The role header omitted while the user id is present.
HEADERS_MISSING_ROLE: Dict[str, str] = {
    "X-User-ID": STORE_CASHIER_ID,
    "Content-Type": "application/json",
}
