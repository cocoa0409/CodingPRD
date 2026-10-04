"""Pre-built role headers for every role the API recognises.

Five of the six roles are opaque: their ``X-User-ID`` is an operator identifier
that the server never compares against a persisted entity, so a shared constant
is the canonical form. ``Group`` is the single entity-backed role — the server
compares ``X-User-ID`` to the ``GroupBooking`` id it is acting on — so callers
must use ``make_group_headers`` with a real group booking id whenever the call
touches a group-owned resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_ops_headers": build_user_headers("test-platform-ops-1", "platform_ops"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    "aquatics_manager_headers": build_user_headers("test-aquatics-manager-1", "AquaticsManager"),
    "gate_attendant_headers": build_user_headers("test-gate-attendant-1", "GateAttendant"),
    # entity_backed role: the shared constant is a fallback for calls that do
    # not depend on group ownership.
    "group_headers": build_user_headers("test-group-1", "Group"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}

# A role name the platform does not recognise, for the authentication gate.
TEST_USERS["unknown_role_headers"] = build_user_headers("test-unknown-1", "NoRole")


def make_group_headers(group_booking_id: str) -> dict:
    """Headers for the entity-backed ``Group`` role acting as
    ``group_booking_id``. Use this for every group-owned resource."""
    return build_user_headers(group_booking_id, "Group")