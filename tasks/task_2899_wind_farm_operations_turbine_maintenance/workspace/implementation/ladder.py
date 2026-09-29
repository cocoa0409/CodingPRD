"""Shared rejection-ladder helpers used by every route module."""

from errors import ApiError
from store import DB

PATH_ERRORS = {
    "farms": "ERR_FARM_NOT_FOUND",
    "turbines": "ERR_TURBINE_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "fault_events": "ERR_FAULT_EVENT_NOT_FOUND",
}


def path_error(table):
    return PATH_ERRORS.get(table, "ERR_PATH_RESOURCE_NOT_FOUND")


def find(table, row_id):
    """Silent path lookup: returns the row or None."""
    return DB.get(table, row_id)


def path_row(table, row_id):
    """Rung 6: resolve a path segment or raise its mapped not-found error."""
    row = DB.get(table, row_id)
    if row is None:
        raise ApiError(path_error(table), "%s does not exist." % row_id)
    return row


def require_found(table, row):
    if row is None:
        raise ApiError(path_error(table), "The requested resource does not exist.")
    return row


def ref_row(table, row_id):
    """Rung 7: resolve a body foreign key or raise ERR_REFERENCE_NOT_FOUND."""
    if row_id is None:
        return None
    row = DB.get(table, row_id)
    if row is None:
        raise ApiError(
            "ERR_REFERENCE_NOT_FOUND", "Referenced resource %s does not exist." % row_id
        )
    return row


def check_version(row, expected, error_id):
    """Rungs 8 and 9: optimistic concurrency."""
    if expected is None:
        return
    if int(expected) != int(row["version"]):
        raise ApiError(
            error_id,
            "Expected version %s but the resource is at version %s."
            % (expected, row["version"]),
        )


def require_state(row, field, allowed, error_id, label="resource"):
    """Rung 10: declared transition guard."""
    if row[field] not in allowed:
        raise ApiError(
            error_id,
            "The %s is in state %s, which does not permit this transition."
            % (label, row[field]),
        )


def invalid_state(message):
    raise ApiError("ERR_INVALID_STATE", message)


def unique_or_bad(table, message, **fields):
    """Uniqueness violations are malformed requests (no dedicated error id)."""
    for row in DB.all(table):
        if all(row.get(k) == v for k, v in fields.items()):
            raise ApiError("ERR_INVALID_REQUEST", message)


def gate(condition, error_id, message):
    if condition:
        raise ApiError(error_id, message)
