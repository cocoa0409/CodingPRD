"""Cross-cutting precedence gates, shared by every route module."""
import db
import middleware
import response
import serialize
from errors import fail

STALE = {
    "employee": "ERR_STALE_EMPLOYEE_VERSION",
    "neighborhood": "ERR_STALE_NEIGHBORHOOD_VERSION",
    "policy_cycle": "ERR_STALE_POLICY_CYCLE_VERSION",
}


def require_owner(actor, employee_id):
    """Priority band 4: Employee identity is entity-backed."""
    if actor.role == middleware.EMPLOYEE and actor.user_id != employee_id:
        fail("ERR_NOT_RESOURCE_OWNER", "caller does not own this resource")


def occ(payload, key, row, kind):
    """Priority bands 6 then 8: the expected-version input is REQUIRED."""
    expected = middleware.req_int(payload, key)
    return expected


def occ_check(expected, row, kind):
    if expected != row["version"]:
        fail(STALE[kind], "%s version is stale" % kind)


def gate_cycle_not_locked(cycle):
    """Priority band 9."""
    if cycle is not None and cycle["posture"] == "LOCKED":
        fail("ERR_CYCLE_LOCKED", "policy cycle is LOCKED")


def gate_cycle_open(cycle):
    """Priority band 9 - classification submit/decision demand posture OPEN."""
    if cycle is not None and cycle["posture"] != "OPEN":
        fail("ERR_CYCLE_LOCKED", "policy cycle posture is not OPEN")


def gate_employee_active(employee):
    """Priority band 11."""
    if employee["status"] != "ACTIVE":
        fail("ERR_EMPLOYEE_NOT_ACTIVE", "employee is not ACTIVE")


def gate_employee_not_separated(employee):
    if employee["status"] not in ("ACTIVE", "ON_LEAVE"):
        fail("ERR_EMPLOYEE_NOT_ACTIVE", "employee is SEPARATED")


def created_order(row):
    return db.seq_key(row)


def paged(kind, rows, sort_key=None, reverse=False):
    limit, offset = middleware.pagination()
    key = sort_key or db.seq_key
    ordered = sorted(rows, key=key, reverse=reverse)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return response.array_response(serialize.dump_all(kind, page), limit, offset, total)


def single(kind, row, status=200):
    return response.object_response(serialize.dump(kind, row), status)
