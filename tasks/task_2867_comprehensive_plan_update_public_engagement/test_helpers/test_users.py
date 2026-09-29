"""Canonical header sets for the five declared roles.

PRD section 2.1: "Identity in this system is deliberately shallow. ... The server
never compares X-User-ID to the id of any stored row and there is no notion of
resource ownership by user."  X-User-ID matters only for the three
segregation-of-duties comparisons of section 2.7, so the identifiers below are
chosen so that an author, an approver and a second approver are always distinct.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMMISSION_CLERK,
    ROLE_ENVIRONMENTAL_CONSULTANT,
    ROLE_PLANNING_DIRECTOR,
    ROLE_PLANNING_STAFF,
    ROLE_STATE_REVIEWER,
)

# Canonical operator identifiers.
STAFF_ID = "staff-1"
STAFF_2_ID = "staff-2"
DIRECTOR_ID = "director-1"
DIRECTOR_2_ID = "director-2"
CONSULTANT_ID = "consultant-1"
CLERK_ID = "clerk-1"
CLERK_2_ID = "clerk-2"
STATE_ID = "state-1"
SHARED_ID = "shared-user"

STAFF = build_user_headers(STAFF_ID, ROLE_PLANNING_STAFF)
STAFF_2 = build_user_headers(STAFF_2_ID, ROLE_PLANNING_STAFF)
DIRECTOR = build_user_headers(DIRECTOR_ID, ROLE_PLANNING_DIRECTOR)
DIRECTOR_2 = build_user_headers(DIRECTOR_2_ID, ROLE_PLANNING_DIRECTOR)
CONSULTANT = build_user_headers(CONSULTANT_ID, ROLE_ENVIRONMENTAL_CONSULTANT)
CLERK = build_user_headers(CLERK_ID, ROLE_COMMISSION_CLERK)
CLERK_2 = build_user_headers(CLERK_2_ID, ROLE_COMMISSION_CLERK)
STATE = build_user_headers(STATE_ID, ROLE_STATE_REVIEWER)

# A PlanningStaff caller and a PlanningDirector caller sharing one X-User-ID:
# the exact shape the segregation-of-duties rule refuses.
STAFF_SHARED = build_user_headers(SHARED_ID, ROLE_PLANNING_STAFF)
DIRECTOR_SHARED = build_user_headers(SHARED_ID, ROLE_PLANNING_DIRECTOR)
CLERK_SHARED = build_user_headers(SHARED_ID, ROLE_COMMISSION_CLERK)

# All five roles, keyed by role name, for read-parity sweeps.
ALL_ROLE_HEADERS = {
    ROLE_PLANNING_STAFF: STAFF,
    ROLE_PLANNING_DIRECTOR: DIRECTOR,
    ROLE_ENVIRONMENTAL_CONSULTANT: CONSULTANT,
    ROLE_COMMISSION_CLERK: CLERK,
    ROLE_STATE_REVIEWER: STATE,
}

# Headers that are structurally invalid for the authentication rung.
NO_HEADERS: dict = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {"X-User-ID": STAFF_ID, "Content-Type": "application/json"}
MISSING_USER_HEADERS = {
    "X-User-Role": ROLE_PLANNING_STAFF,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers(STAFF_ID, "CityAttorney")


def headers_for(role: str, user_id: str) -> dict:
    """Build an arbitrary (role, user_id) pair; used by duties tests."""
    return build_user_headers(user_id, role)
