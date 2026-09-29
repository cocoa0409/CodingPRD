"""Acting identities for the mountain operations API.

Every request carries X-User-ID and X-User-Role. For the five operator roles
the user identifier is opaque and is never resolved to a row, so a stable
placeholder string is enough. For the Patroller role the user identifier is the
id of the acting patroller row, so those headers must be built per patroller
with make_patroller_headers().
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DIRECTOR,
    ROLE_GROOMING,
    ROLE_GUEST_SERVICES,
    ROLE_LIFT_OPS,
    ROLE_PATROLLER,
    ROLE_SNOWMAKING,
)

# ─── Opaque operator identifiers ──────────────────────
DIRECTOR_USER_ID = "user-director-01"
SNOWMAKING_USER_ID = "user-snowmaking-01"
GROOMING_USER_ID = "user-grooming-01"
LIFT_OPS_USER_ID = "user-liftops-01"
GUEST_SERVICES_USER_ID = "user-guest-01"

# A second opaque identity per role, for rules that compare two user ids to
# one another as strings.
SECOND_DIRECTOR_USER_ID = "user-director-02"
SECOND_GROOMING_USER_ID = "user-grooming-02"

DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, ROLE_DIRECTOR)
SNOWMAKING_HEADERS = build_user_headers(SNOWMAKING_USER_ID, ROLE_SNOWMAKING)
GROOMING_HEADERS = build_user_headers(GROOMING_USER_ID, ROLE_GROOMING)
LIFT_OPS_HEADERS = build_user_headers(LIFT_OPS_USER_ID, ROLE_LIFT_OPS)
GUEST_SERVICES_HEADERS = build_user_headers(GUEST_SERVICES_USER_ID, ROLE_GUEST_SERVICES)

SECOND_DIRECTOR_HEADERS = build_user_headers(SECOND_DIRECTOR_USER_ID, ROLE_DIRECTOR)
SECOND_GROOMING_HEADERS = build_user_headers(SECOND_GROOMING_USER_ID, ROLE_GROOMING)


def make_patroller_headers(patroller_id: str) -> Dict[str, str]:
    """Headers for the Patroller role, whose X-User-ID is a patroller row id."""
    return build_user_headers(patroller_id, ROLE_PATROLLER)


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DIRECTOR)


def make_snowmaking_headers(user_id: str = SNOWMAKING_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SNOWMAKING)


def make_grooming_headers(user_id: str = GROOMING_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_GROOMING)


def make_lift_ops_headers(user_id: str = LIFT_OPS_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LIFT_OPS)


def make_guest_services_headers(user_id: str = GUEST_SERVICES_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_GUEST_SERVICES)


def headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for any role. A Patroller caller must supply a patroller row id."""
    defaults = {
        ROLE_DIRECTOR: DIRECTOR_USER_ID,
        ROLE_SNOWMAKING: SNOWMAKING_USER_ID,
        ROLE_GROOMING: GROOMING_USER_ID,
        ROLE_LIFT_OPS: LIFT_OPS_USER_ID,
        ROLE_GUEST_SERVICES: GUEST_SERVICES_USER_ID,
        ROLE_PATROLLER: "user-patroller-unresolved",
    }
    return build_user_headers(user_id or defaults[role], role)


# ─── Malformed authentication headers ─────────────────
NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_DIRECTOR,
    "Content-Type": "application/json",
}
MISSING_ROLE_HEADERS = {
    "X-User-ID": DIRECTOR_USER_ID,
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADERS = build_user_headers("", ROLE_DIRECTOR)
EMPTY_ROLE_HEADERS = build_user_headers(DIRECTOR_USER_ID, "")
UNRECOGNISED_ROLE_HEADERS = build_user_headers(DIRECTOR_USER_ID, "SkiSchoolInstructor")

# Every acting role that is not tied to a persisted row, keyed by role name.
OPAQUE_ROLE_HEADERS = {
    ROLE_DIRECTOR: DIRECTOR_HEADERS,
    ROLE_SNOWMAKING: SNOWMAKING_HEADERS,
    ROLE_GROOMING: GROOMING_HEADERS,
    ROLE_LIFT_OPS: LIFT_OPS_HEADERS,
    ROLE_GUEST_SERVICES: GUEST_SERVICES_HEADERS,
}
