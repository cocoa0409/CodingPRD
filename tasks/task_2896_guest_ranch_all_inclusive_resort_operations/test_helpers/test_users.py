"""Pre-built role headers for every role the PRD declares.

Two of the six roles carry entity-backed identity:

* ``ActivityGuide`` — ``X-User-ID`` must be the acting StaffMember's id.
* ``Guest`` — ``X-User-ID`` must be the acting Guest's id.

For those two roles the shared ``TEST_USERS`` constants are only safe on calls
that do not exercise ownership (for example a 401/403/404 probe).  Any
ownership-gated call MUST use the matching ``make_*_headers(entity_id)``
builder with the real entity id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --------------------------------------------------------------------------
# Shared constants — opaque roles, plus non-ownership probes for the two
# entity-backed roles.
# --------------------------------------------------------------------------

TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque identity — the shared constant is the canonical form
    "ranch_manager_headers": build_user_headers("test-ranch-manager-1", "RanchManager"),
    "reservations_agent_headers": build_user_headers(
        "test-reservations-agent-1", "ReservationsAgent"
    ),
    "horse_program_director_headers": build_user_headers(
        "test-horse-director-1", "HorseProgramDirector"
    ),
    # SafetyOfficer is opaque, but incident close demands a different acting
    # X-User-ID from the one that disposed, so two distinct officers exist.
    "safety_officer_headers": build_user_headers("test-safety-officer-1", "SafetyOfficer"),
    "safety_officer_two_headers": build_user_headers(
        "test-safety-officer-2", "SafetyOfficer"
    ),
    # entity-backed identity — fallbacks for non-ownership tests only
    "activity_guide_headers": build_user_headers("test-activity-guide-1", "ActivityGuide"),
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
}

# Convenient aliases used throughout the suite.
RANCH_MANAGER = TEST_USERS["ranch_manager_headers"]
RESERVATIONS_AGENT = TEST_USERS["reservations_agent_headers"]
HORSE_PROGRAM_DIRECTOR = TEST_USERS["horse_program_director_headers"]
SAFETY_OFFICER = TEST_USERS["safety_officer_headers"]
SAFETY_OFFICER_TWO = TEST_USERS["safety_officer_two_headers"]

SAFETY_OFFICER_ONE_USER_ID = "test-safety-officer-1"
SAFETY_OFFICER_TWO_USER_ID = "test-safety-officer-2"


# --------------------------------------------------------------------------
# Per-instance builders.
# --------------------------------------------------------------------------

def make_ranch_manager_headers(user_id: str = "test-ranch-manager-1") -> Dict[str, str]:
    """RanchManager headers (opaque identity)."""
    return build_user_headers(user_id, "RanchManager")


def make_reservations_agent_headers(user_id: str = "test-reservations-agent-1") -> Dict[str, str]:
    """ReservationsAgent headers (opaque identity)."""
    return build_user_headers(user_id, "ReservationsAgent")


def make_horse_program_director_headers(user_id: str = "test-horse-director-1") -> Dict[str, str]:
    """HorseProgramDirector headers (opaque identity)."""
    return build_user_headers(user_id, "HorseProgramDirector")


def make_safety_officer_headers(user_id: str = "test-safety-officer-1") -> Dict[str, str]:
    """SafetyOfficer headers.  Pass a distinct user id for the officer that
    closes a report so it differs from the one that disposed it."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_activity_guide_headers(staff_member_id: str) -> Dict[str, str]:
    """ActivityGuide headers.  ``staff_member_id`` MUST be the real
    StaffMember id whose guide assignment covers the addressed slot."""
    return build_user_headers(staff_member_id, "ActivityGuide")


def make_guest_headers(guest_id: str) -> Dict[str, str]:
    """Guest headers.  ``guest_id`` MUST be the real Guest id whose own
    record, booking or seat is being addressed."""
    return build_user_headers(guest_id, "Guest")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary role/id pair — used by unknown-role and blank-header probes."""
    return build_user_headers(user_id, role)


# Header variants for the auth-rejection probes.  A blank value must be the
# empty string: a whitespace-only header value is rejected by the HTTP client
# itself and would never reach the API.
MISSING_BOTH_HEADERS: Dict[str, str] = {}
MISSING_ROLE_HEADER: Dict[str, str] = {"X-User-ID": "test-ranch-manager-1"}
MISSING_USER_ID_HEADER: Dict[str, str] = {"X-User-Role": "RanchManager"}
EMPTY_ROLE_HEADER: Dict[str, str] = {
    "X-User-ID": "test-ranch-manager-1",
    "X-User-Role": "",
}
EMPTY_USER_ID_HEADER: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": "RanchManager",
}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    "test-unknown-1", "TrailBossEmeritus"
)

ALL_ROLE_NAMES = [
    "RanchManager",
    "ReservationsAgent",
    "HorseProgramDirector",
    "ActivityGuide",
    "Guest",
    "SafetyOfficer",
]
