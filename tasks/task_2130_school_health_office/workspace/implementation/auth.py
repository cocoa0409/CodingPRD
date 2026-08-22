"""Ladder positions 1-4: authentication, authorisation, ownership, existence."""
from flask import request

from errors import fail
from store import db

ROLES = (
    "DistrictHealthAdmin",
    "SchoolNurse",
    "HealthAide",
    "Guardian",
    "SchoolPhysician",
    "RecordsOfficer",
)

ALL_READ_ROLES = ["DistrictHealthAdmin", "SchoolNurse", "HealthAide",
                  "SchoolPhysician", "RecordsOfficer"]
ALL_READ_ROLES_WITH_GUARDIAN = ALL_READ_ROLES + ["Guardian"]


def principal():
    """Position 1 - both headers present and the role is one of the six."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    return user_id, role


def require_role(role, allowed):
    """Position 2 - the acting role appears in the endpoint's role list."""
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)


def authorize(allowed):
    user_id, role = principal()
    require_role(role, allowed)
    return user_id, role


def guardian_owns(row, user_id, role, field="student_id"):
    """Position 3 - a Guardian's X-User-ID equals the target row's student_id."""
    if role != "Guardian" or row is None:
        return
    if row.get(field) != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Guardian may only act on their own child's records.")


def nurse_owns(row, user_id, role, field):
    """Position 3 - a nurse's or aide's X-User-ID equals the named field."""
    if role not in ("SchoolNurse", "HealthAide") or row is None:
        return
    if row.get(field) != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the owning nurse may perform this step.")


# ---------------------------------------------------------------------------
# Position 4 - existence
# ---------------------------------------------------------------------------

def find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, collection).get(row_id)


def must_exist(collection, row_id, label=None):
    row = find(collection, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "%s %s does not exist." % (label or collection, row_id))
    return row


def rows(collection):
    return list(getattr(db, collection).values())


def insert(collection, record):
    getattr(db, collection)[record["id"]] = record
    return record


def resolve(collection, value, label=None):
    """Position 4 for an optional-or-required foreign key: a value that was not
    supplied is left to the payload-shape band at position 5."""
    if value is None:
        return None
    return must_exist(collection, value, label)
