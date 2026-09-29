"""Shared ladder guards (PRD 2.8). Each helper raises exactly the error the rung
it belongs to declares."""
import calc
from db import db
from errors import ApiError


def lookup(table, ident, error_id, label):
    """Rung 8 -- path identifiers resolved strictly left to right."""
    row = table.get(ident) if isinstance(ident, str) else None
    if row is None:
        raise ApiError(error_id, "%s '%s' does not exist." % (label, ident))
    return row


def maybe(table, ident):
    """Best-effort resolution for the authorization rungs (3-6), which run ahead
    of the existence rung and must not report a 404 themselves."""
    if not isinstance(ident, str):
        return None
    return table.get(ident)


def reference(table, ident, label):
    """Rung 9 -- foreign keys carried in the request body."""
    row = table.get(ident) if isinstance(ident, str) else None
    if row is None:
        raise ApiError("ERR_INVALID_REFERENCE", "%s '%s' does not exist." % (label, ident))
    return row


def require_active_project(project):
    """Rung 11 -- owning-project status."""
    if project["status"] != "ACTIVE":
        raise ApiError("ERR_PROJECT_NOT_ACTIVE",
                       "The owning project is in %s, not ACTIVE." % project["status"])


def require_project_not_closed(project):
    """PRD 3.1: for multiplier creation the only status that triggers
    ERR_PROJECT_NOT_ACTIVE is CLOSED."""
    if project["status"] == "CLOSED":
        raise ApiError("ERR_PROJECT_NOT_ACTIVE", "The owning project is CLOSED.")


def invalid_state(msg):
    """Rung 12."""
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg)


def require_period_open(project, service_date, field):
    """Rung 14 -- PRD 2.6: a charge whose service date falls on or before
    locked_through_date may neither be created nor approved."""
    lock = project["locked_through_date"]
    if lock is not None and service_date <= lock:
        raise ApiError("ERR_PERIOD_LOCKED",
                       "%s falls inside the period locked through %s." % (field, lock.isoformat()))


def require_leaf(phase):
    """Rung 15 -- only leaves carry money (PRD 3.1)."""
    if not calc.phase_is_leaf(phase):
        raise ApiError("ERR_PHASE_NOT_LEAF", "Charges may only be booked to a leaf phase.")


def require_project_version(project, expected):
    """Rung 10 -- PRD 2.7 optimistic concurrency on the project version."""
    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION",
                       "expected_project_version %s does not match the project's current version %s."
                       % (expected, project["version"]))
