"""Pre-built auth headers for every role, plus per-identity header builders.

Opaque operator roles (director, coordinator, supervisor) may reuse a stable
X-User-ID.  A StaffMember's X-User-ID must be the id of the worker record being
acted for, so worker headers are always built from a live staff member id via
make_staff_member_headers().
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COORDINATOR,
    ROLE_DIRECTOR,
    ROLE_STAFF_MEMBER,
    ROLE_SUPERVISOR,
)

DIRECTOR_USER_ID = "u-director-1"
COORDINATOR_USER_ID = "u-coordinator-1"
SUPERVISOR_USER_ID = "u-supervisor-1"

DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, ROLE_DIRECTOR)
COORDINATOR_HEADERS = build_user_headers(COORDINATOR_USER_ID, ROLE_COORDINATOR)
SUPERVISOR_HEADERS = build_user_headers(SUPERVISOR_USER_ID, ROLE_SUPERVISOR)

TEST_USERS = {
    ROLE_DIRECTOR: DIRECTOR_HEADERS,
    ROLE_COORDINATOR: COORDINATOR_HEADERS,
    ROLE_SUPERVISOR: SUPERVISOR_HEADERS,
}


def make_director_headers(user_id: str = DIRECTOR_USER_ID):
    return build_user_headers(user_id, ROLE_DIRECTOR)


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID):
    return build_user_headers(user_id, ROLE_COORDINATOR)


def make_supervisor_headers(user_id: str = SUPERVISOR_USER_ID):
    return build_user_headers(user_id, ROLE_SUPERVISOR)


def make_staff_member_headers(staff_member_id: str):
    """Worker headers: X-User-ID is the id of the acting worker record."""
    return build_user_headers(staff_member_id, ROLE_STAFF_MEMBER)


def make_role_headers(role: str, user_id: str = "u-generic-1"):
    return build_user_headers(user_id, role)


def headers_missing_role(user_id: str = DIRECTOR_USER_ID):
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = ROLE_DIRECTOR):
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_user_id(role: str = ROLE_DIRECTOR):
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = DIRECTOR_USER_ID):
    return build_user_headers(user_id, "VenueJanitor")
