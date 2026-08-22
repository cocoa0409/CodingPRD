"""Shared route helpers: path/body identifier resolution and paging."""

from db import db
from errors import ApiError
from services.domain import by_seq

_NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "chambers": "ERR_CHAMBER_NOT_FOUND",
    "recipes": "ERR_RECIPE_NOT_FOUND",
    "qualifications": "ERR_QUALIFICATION_NOT_FOUND",
    "lots": "ERR_LOT_NOT_FOUND",
    "cycles": "ERR_CYCLE_NOT_FOUND",
    "load_positions": "ERR_LOAD_POSITION_NOT_FOUND",
    "indicators": "ERR_INDICATOR_NOT_FOUND",
    "aeration_records": "ERR_AERATION_RECORD_NOT_FOUND",
    "adverse_events": "ERR_ADVERSE_EVENT_NOT_FOUND",
}


def fetch(collection, record_id):
    table = getattr(db, collection)
    record = table.get(record_id)
    if record is None:
        raise ApiError(_NOT_FOUND[collection])
    return record


def peek(collection, record_id):
    return getattr(db, collection).get(record_id)


def paginate(rows, limit, offset):
    ordered = by_seq(rows)
    total = len(ordered)
    return ordered[offset:offset + limit], total
