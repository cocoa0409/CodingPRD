"""Acting principals and their auth headers.

PRD 2.1 splits the eight roles into two identity families. The six operator
roles carry an opaque `X-User-ID` that "is not tied to any persisted entity",
so each gets one fixed constant header dict. The two agency-backed roles
(`AgencyRadioManager`, `Dispatcher`) carry the `id` of the acting
`MemberAgency`, so they MUST be built per agency with the builders below — never
from a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENCY_RADIO_MANAGER,
    ROLE_CHANGE_CONTROL_BOARD,
    ROLE_DISPATCHER,
    ROLE_FLEET_ENGINEER,
    ROLE_KEY_CUSTODIAN,
    ROLE_RF_ENGINEER,
    ROLE_SECURITY_OFFICER,
    ROLE_SYSTEM_ADMIN,
    UNDECLARED_ROLE,
)

# --- Opaque operator identifiers -------------------------------------------

SYSTEM_ADMIN_ID = "admin-1"
RF_ENGINEER_ID = "rf-1"
FLEET_ENGINEER_ID = "fe-1"
CHANGE_CONTROL_BOARD_ID = "ccb-1"
CHANGE_CONTROL_BOARD_ID_2 = "ccb-2"
KEY_CUSTODIAN_ID = "kc-1"
KEY_CUSTODIAN_ID_2 = "kc-2"
SECURITY_OFFICER_ID = "so-1"
SECURITY_OFFICER_ID_2 = "so-2"
FLEET_ENGINEER_ID_2 = "fe-2"

# An identifier presented alongside a role outside the declared set of eight.
UNDECLARED_ROLE_USER_ID = "intern-1"

# --- Fixed operator header dicts -------------------------------------------

SYSTEM_ADMIN = build_user_headers(SYSTEM_ADMIN_ID, ROLE_SYSTEM_ADMIN)
RF_ENGINEER = build_user_headers(RF_ENGINEER_ID, ROLE_RF_ENGINEER)
FLEET_ENGINEER = build_user_headers(FLEET_ENGINEER_ID, ROLE_FLEET_ENGINEER)
FLEET_ENGINEER_2 = build_user_headers(FLEET_ENGINEER_ID_2, ROLE_FLEET_ENGINEER)
CHANGE_CONTROL_BOARD = build_user_headers(
    CHANGE_CONTROL_BOARD_ID, ROLE_CHANGE_CONTROL_BOARD
)
CHANGE_CONTROL_BOARD_2 = build_user_headers(
    CHANGE_CONTROL_BOARD_ID_2, ROLE_CHANGE_CONTROL_BOARD
)
KEY_CUSTODIAN = build_user_headers(KEY_CUSTODIAN_ID, ROLE_KEY_CUSTODIAN)
KEY_CUSTODIAN_2 = build_user_headers(KEY_CUSTODIAN_ID_2, ROLE_KEY_CUSTODIAN)
SECURITY_OFFICER = build_user_headers(SECURITY_OFFICER_ID, ROLE_SECURITY_OFFICER)
SECURITY_OFFICER_2 = build_user_headers(SECURITY_OFFICER_ID_2, ROLE_SECURITY_OFFICER)

# A well-formed header pair whose role is not one of the eight declared roles.
UNDECLARED_ROLE_HEADERS = build_user_headers(UNDECLARED_ROLE_USER_ID, UNDECLARED_ROLE)


# --- Agency-backed header builders -----------------------------------------


def make_agency_radio_manager_headers(agency_id: str) -> Dict[str, str]:
    """Headers for the `AgencyRadioManager` of the agency named by `agency_id`."""
    return build_user_headers(agency_id, ROLE_AGENCY_RADIO_MANAGER)


def make_dispatcher_headers(agency_id: str) -> Dict[str, str]:
    """Headers for the `Dispatcher` of the agency named by `agency_id`."""
    return build_user_headers(agency_id, ROLE_DISPATCHER)


def make_operator_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary operator identifier and role pair."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Headers for any role with an explicit acting identifier."""
    return build_user_headers(user_id, role)


# --- Malformed authentication header variants ------------------------------
# PRD 2.1: "Both headers must be present and must be non-empty strings; a
# request missing either header, or supplying an empty string for either, is
# rejected with `ERR_UNAUTHENTICATED`." Empty means the empty string "" — never
# a whitespace-only value, which is not a valid HTTP header value at all.

MISSING_USER_ID = {"X-User-Role": ROLE_SYSTEM_ADMIN, "Content-Type": "application/json"}
MISSING_USER_ROLE = {"X-User-ID": SYSTEM_ADMIN_ID, "Content-Type": "application/json"}
EMPTY_USER_ID = {
    "X-User-ID": "",
    "X-User-Role": ROLE_SYSTEM_ADMIN,
    "Content-Type": "application/json",
}
EMPTY_USER_ROLE = {
    "X-User-ID": SYSTEM_ADMIN_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def headers_for_all_roles(agency_id: str) -> Dict[str, Dict[str, str]]:
    """One header dict per declared role.

    The two agency-backed roles are bound to `agency_id` because PRD 2.1
    requires their `X-User-ID` to resolve to an existing `MemberAgency`.
    """
    return {
        ROLE_SYSTEM_ADMIN: SYSTEM_ADMIN,
        ROLE_RF_ENGINEER: RF_ENGINEER,
        ROLE_FLEET_ENGINEER: FLEET_ENGINEER,
        ROLE_CHANGE_CONTROL_BOARD: CHANGE_CONTROL_BOARD,
        ROLE_KEY_CUSTODIAN: KEY_CUSTODIAN,
        ROLE_SECURITY_OFFICER: SECURITY_OFFICER,
        ROLE_AGENCY_RADIO_MANAGER: make_agency_radio_manager_headers(agency_id),
        ROLE_DISPATCHER: make_dispatcher_headers(agency_id),
    }
