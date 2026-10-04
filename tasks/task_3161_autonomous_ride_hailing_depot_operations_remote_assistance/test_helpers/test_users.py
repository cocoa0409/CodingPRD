"""Caller identities for every role in the interface.

Identity in this system is entirely opaque: for all six roles the
``X-User-ID`` is an operator identifier that the server authenticates and
uses for permission evaluation but never compares against a persisted
entity's ``id``.  There is exactly one place the value is persisted — the
acknowledging operator recorded on an assistance session as
``op_user_id`` — and no ownership check anywhere derives from it.

Because no role is entity-backed, every role's headers are a shared
constant.  ``headers_for`` exists for tests that need a second operator
identity of the same role (or a deliberately cross-wired one).
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DEPOT_TECHNICIAN,
    ROLE_FLEET_OPERATIONS,
    ROLE_MAPPING_ENGINEER,
    ROLE_REMOTE_ASSISTANCE_OPERATOR,
    ROLE_SAFETY_REVIEWER,
    ROLE_TERRITORY_PLANNER,
)

# Opaque operator identifiers, one per role.
FLEET_USER_ID = "fleet-ops-1"
DEPOT_USER_ID = "depot-tech-1"
ASSIST_USER_ID = "assist-op-1"
ASSIST_USER_ID_2 = "assist-op-2"
PLANNER_USER_ID = "planner-1"
SAFETY_USER_ID = "safety-1"
MAPPING_USER_ID = "mapping-1"

# Ready-made header sets.
FLEET = build_user_headers(FLEET_USER_ID, ROLE_FLEET_OPERATIONS)
DEPOT = build_user_headers(DEPOT_USER_ID, ROLE_DEPOT_TECHNICIAN)
ASSIST = build_user_headers(ASSIST_USER_ID, ROLE_REMOTE_ASSISTANCE_OPERATOR)
ASSIST_2 = build_user_headers(ASSIST_USER_ID_2, ROLE_REMOTE_ASSISTANCE_OPERATOR)
PLANNER = build_user_headers(PLANNER_USER_ID, ROLE_TERRITORY_PLANNER)
SAFETY = build_user_headers(SAFETY_USER_ID, ROLE_SAFETY_REVIEWER)
MAPPING = build_user_headers(MAPPING_USER_ID, ROLE_MAPPING_ENGINEER)

# Absent / malformed header sets for the authentication layer.
NO_HEADERS = {}
MALFORMED_ROLE_HEADERS = {"X-User-ID": "ghost-1", "X-User-Role": "ChiefFleetOfficer"}
MISSING_ID_HEADERS = {"X-User-Role": ROLE_FLEET_OPERATIONS}
MISSING_ROLE_HEADERS = {"X-User-ID": "ghost-1"}


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including deliberate cross-wirings."""
    return build_user_headers(user_id, role)


TEST_USERS = {
    "fleet_operations_headers": FLEET,
    "depot_technician_headers": DEPOT,
    "remote_assistance_headers": ASSIST,
    "territory_planner_headers": PLANNER,
    "safety_reviewer_headers": SAFETY,
    "mapping_engineer_headers": MAPPING,
}