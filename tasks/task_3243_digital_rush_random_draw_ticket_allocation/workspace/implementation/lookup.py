"""Path-segment resolution (left to right) and body-reference resolution."""

from db import DB
from errors import ApiError

NOT_FOUND = {
    "production": "ERR_PRODUCTION_NOT_FOUND",
    "performance": "ERR_PERFORMANCE_NOT_FOUND",
    "allocation": "ERR_ALLOCATION_NOT_FOUND",
    "purchase": "ERR_PURCHASE_NOT_FOUND",
    "draw_entry": "ERR_DRAW_ENTRY_NOT_FOUND",
    "seat_hold": "ERR_HOLD_NOT_FOUND",
    "queue_position": "ERR_QUEUE_POSITION_NOT_FOUND",
    "desk": "ERR_DESK_NOT_FOUND",
    "refund": "ERR_REFUND_NOT_FOUND",
    "exchange": "ERR_EXCHANGE_NOT_FOUND",
    "patron": "ERR_PATRON_NOT_FOUND",
    "market": "ERR_MARKET_NOT_FOUND",
}


def fetch(kind, row_id):
    """Third rung: a path segment that does not resolve names its own resource."""
    row = DB.get(kind, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


def production(row_id):
    return fetch("production", row_id)


def performance(row_id):
    return fetch("performance", row_id)


def allocation(row_id):
    return fetch("allocation", row_id)


def purchase(row_id):
    return fetch("purchase", row_id)


def draw_entry(row_id):
    return fetch("draw_entry", row_id)


def seat_hold(row_id):
    return fetch("seat_hold", row_id)


def queue_position(row_id):
    return fetch("queue_position", row_id)


def refund(row_id):
    return fetch("refund", row_id)


def exchange(row_id):
    return fetch("exchange", row_id)


def patron(row_id):
    return fetch("patron", row_id)


def market(row_id):
    return fetch("market", row_id)


def market_by_code(code):
    """Fourth rung: a body-supplied market code that resolves to nothing."""
    for candidate in DB.all("market"):
        if candidate["market_code"] == code:
            return candidate
    raise ApiError("ERR_REFERENCE_NOT_FOUND")


def desk_by_code(code):
    for candidate in DB.all("desk"):
        if candidate["desk_code"] == code:
            return candidate
    raise ApiError("ERR_REFERENCE_NOT_FOUND")


def production_of(performance_row):
    return DB.get("production", performance_row["production_id"])


def performance_of_allocation(allocation_row):
    return DB.get("performance", allocation_row["performance_id"])


def market_of_performance(performance_row):
    for candidate in DB.all("market"):
        if candidate["market_code"] == performance_row["market_code"]:
            return candidate
    return None


def owner_production(performance_row):
    return DB.get("production", performance_row["production_id"])