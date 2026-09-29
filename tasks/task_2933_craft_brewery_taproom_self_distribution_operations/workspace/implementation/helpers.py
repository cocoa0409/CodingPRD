"""Shared lookup, uniqueness and gating helpers used by the route modules."""

import derive
import store
import validation
from errors import ApiError
from store import DB

NOT_FOUND = {
    "beers": "ERR_BEER_NOT_FOUND",
    "tanks": "ERR_TANK_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "runs": "ERR_PACKAGING_RUN_NOT_FOUND",
    "kegs": "ERR_KEG_ASSET_NOT_FOUND",
    "pours": "ERR_TAPROOM_POUR_NOT_FOUND",
    "licenses": "ERR_STATE_LICENSE_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
    "permits": "ERR_EVENT_PERMIT_NOT_FOUND",
}

UNIQUE_FIELD = {
    "beers": "name",
    "tanks": "code",
    "batches": "batch_code",
    "runs": "run_code",
    "kegs": "keg_serial",
    "orders": "order_code",
    "licenses": "state_code",
}


def find(collection, identifier):
    row = DB[collection].get(identifier)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def brewery():
    row = DB["brewery"]
    if row is None:
        raise ApiError("ERR_BREWERY_NOT_FOUND")
    return row


def unique(collection, value):
    field = UNIQUE_FIELD[collection]
    for row in DB[collection].values():
        if row.get(field) == value:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "A %s with %s '%s' already exists."
                           % (collection[:-1], field, value))


def require_notice_active():
    row = brewery()
    if row.get("notice_status") != "ACTIVE":
        raise ApiError("ERR_NOTICE_NOT_ACTIVE")
    return row


def insert(collection, row):
    DB[collection][row["id"]] = row
    return row


def now():
    return store.clock_now()


def listing(collection, serializer, predicate=None):
    limit, offset = validation.pagination()
    rows = store.ordered(list(DB[collection].values()))
    if predicate is not None:
        rows = [row for row in rows if predicate(row)]
    total = len(rows)
    window = rows[offset:offset + limit]
    return [serializer(row) for row in window], limit, offset, total


def matches(row, field, value):
    if value is None:
        return True
    return row.get(field) == value


def derived_state_code(licence_id):
    licence = DB["licenses"].get(licence_id)
    return None if licence is None else licence.get("state_code")


def license_window_guard(licence):
    """Rung 14: licence validity window against the logical clock."""
    current = store.clock_now()
    if current < licence["effective_from_utc"]:
        raise ApiError("ERR_LICENSE_NOT_YET_EFFECTIVE")
    if current >= licence["expires_at_utc"]:
        raise ApiError("ERR_LICENSE_EXPIRED")


def license_active_guard(licence):
    """Rung 11: licence status gate."""
    if licence.get("status") != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE")


def beer_formula_guard(beer):
    if not derive.formula_ok(beer):
        raise ApiError("ERR_FORMULA_NOT_APPROVED")


def beer_label_guard(beer):
    if beer.get("label_state") != "COLA_APPROVED":
        raise ApiError("ERR_LABEL_NOT_APPROVED")
