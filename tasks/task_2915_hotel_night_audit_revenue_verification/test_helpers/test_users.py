"""Identity headers for the six declared roles.

Every request carries X-User-ID and X-User-Role. Five of the six roles have an
opaque identity, so any non-empty string is a legal X-User-ID. OutletManager is
different: its identity is the id of an existing Outlet row, so its X-User-ID
must be the outlet's own id.

Distinct actors get distinct X-User-ID values on purpose, because several rules
compare the acting user against the user recorded on a row (the requester of an
allowance, the declarer of a settlement batch, the filer of a document, the
poster of a journal line).
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONTROLLER,
    ROLE_FRONT_DESK_AGENT,
    ROLE_NIGHT_AUDITOR,
    ROLE_OUTLET_MANAGER,
    ROLE_PROPERTY_ADMIN,
    ROLE_REVENUE_MANAGER,
)
from .types import Headers

# --- canonical opaque user ids ----------------------------------------------

U_ADMIN_1 = "u_admin_1"
U_ADMIN_2 = "u_admin_2"
U_NA_1 = "u_na_1"
U_NA_2 = "u_na_2"
U_FD_1 = "u_fd_1"
U_FD_2 = "u_fd_2"
U_RM_1 = "u_rm_1"
U_RM_2 = "u_rm_2"
U_CTL_1 = "u_ctl_1"
U_CTL_2 = "u_ctl_2"


# --- role header builders ----------------------------------------------------


def make_property_admin_headers(user_id: str = U_ADMIN_1) -> Headers:
    return build_user_headers(user_id, ROLE_PROPERTY_ADMIN)


def make_night_auditor_headers(user_id: str = U_NA_1) -> Headers:
    return build_user_headers(user_id, ROLE_NIGHT_AUDITOR)


def make_front_desk_headers(user_id: str = U_FD_1) -> Headers:
    return build_user_headers(user_id, ROLE_FRONT_DESK_AGENT)


def make_revenue_manager_headers(user_id: str = U_RM_1) -> Headers:
    return build_user_headers(user_id, ROLE_REVENUE_MANAGER)


def make_controller_headers(user_id: str = U_CTL_1) -> Headers:
    return build_user_headers(user_id, ROLE_CONTROLLER)


def make_outlet_manager_headers(outlet_id: str) -> Headers:
    """An OutletManager acts as the outlet itself: X-User-ID is the Outlet id."""
    return build_user_headers(outlet_id, ROLE_OUTLET_MANAGER)


def make_headers(role: str, user_id: str) -> Headers:
    """Build headers for an arbitrary role/user pair."""
    return build_user_headers(user_id, role)


# --- ready-made header dicts for the common actors --------------------------

ADMIN = make_property_admin_headers(U_ADMIN_1)
AUDITOR = make_night_auditor_headers(U_NA_1)
AUDITOR_2 = make_night_auditor_headers(U_NA_2)
FRONT_DESK = make_front_desk_headers(U_FD_1)
FRONT_DESK_2 = make_front_desk_headers(U_FD_2)
REVENUE_MANAGER = make_revenue_manager_headers(U_RM_1)
REVENUE_MANAGER_2 = make_revenue_manager_headers(U_RM_2)
CONTROLLER = make_controller_headers(U_CTL_1)
CONTROLLER_2 = make_controller_headers(U_CTL_2)

# The default opaque user id used for each role when a test only cares about the
# role and not about which individual is acting.
DEFAULT_USER_FOR_ROLE = {
    ROLE_PROPERTY_ADMIN: U_ADMIN_1,
    ROLE_NIGHT_AUDITOR: U_NA_1,
    ROLE_FRONT_DESK_AGENT: U_FD_1,
    ROLE_REVENUE_MANAGER: U_RM_1,
    ROLE_CONTROLLER: U_CTL_1,
}


def headers_for_role(role: str, outlet_id: str = None) -> Headers:
    """Headers for a role using its default actor.

    OutletManager needs an outlet id, because its identity is that outlet.
    """
    if role == ROLE_OUTLET_MANAGER:
        assert outlet_id is not None, "OutletManager headers need an outlet id"
        return make_outlet_manager_headers(outlet_id)
    return build_user_headers(DEFAULT_USER_FOR_ROLE[role], role)


# A header pair that omits X-User-ID entirely.
NO_USER_ID_HEADERS = {
    "X-User-Role": ROLE_NIGHT_AUDITOR,
    "Content-Type": "application/json",
}

# A header pair whose X-User-ID is the empty string. requests refuses to send a
# header made only of whitespace, so an "empty" header must be exactly "".
EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_NIGHT_AUDITOR,
    "Content-Type": "application/json",
}

NO_ROLE_HEADERS = {
    "X-User-ID": U_NA_1,
    "Content-Type": "application/json",
}

EMPTY_ROLE_HEADERS = {
    "X-User-ID": U_NA_1,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": U_NA_1,
    "X-User-Role": "GeneralManager",
    "Content-Type": "application/json",
}
