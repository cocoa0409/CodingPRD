"""Rejection-ladder ranks 3, 4 and 5 helpers.

Rank 3/4 (existence, 404) always run BEFORE rank 5 (ERR_INVALID_REQUEST, 400),
so foreign-key lookups here only fire when the field is actually present.
"""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from store import D, db, is_futures_month, parse_date, parse_ts

COMMODITIES = ("CORN", "SOYBEANS", "HRW_WHEAT")
CONTRACT_TYPES = ("CASH", "HTA", "BASIS", "DEFERRED")
SETTLEMENT_BASES = ("SHRINK_FIRST", "GROSS_GRADE")
SIDES = ("SHORT", "LONG")
COMPONENTS = ("FUTURES", "BASIS")
DAMAGES_METHODS = ("MARKET_LOSS", "REPLACEMENT_COST")
TIER_FACTORS = ("MOISTURE", "TEST_WEIGHT", "FOREIGN_MATERIAL", "DAMAGE")
TIER_DIRECTIONS = ("ABOVE", "BELOW")


def body():
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        return {"__invalid__": True}
    return payload


# --------------------------------------------------------------------------
# Rank 3/4 — existence
# --------------------------------------------------------------------------
_COLLECTION_ERRORS = {
    "trading_desks": "ERR_TRADING_DESK_NOT_FOUND",
    "elevator_locations": "ERR_LOCATION_NOT_FOUND",
    "discount_schedules": "ERR_DISCOUNT_SCHEDULE_NOT_FOUND",
    "risk_limits": "ERR_RISK_LIMIT_NOT_FOUND",
    "rail_fleets": "ERR_RAIL_FLEET_NOT_FOUND",
    "bids": "ERR_BID_NOT_FOUND",
    "hedge_positions": "ERR_HEDGE_POSITION_NOT_FOUND",
    "purchase_contracts": "ERR_CONTRACT_NOT_FOUND",
    "pricing_orders": "ERR_PRICING_ORDER_NOT_FOUND",
    "margin_calls": "ERR_MARGIN_CALL_NOT_FOUND",
    "delivery_tickets": "ERR_DELIVERY_TICKET_NOT_FOUND",
    "freight_bookings": "ERR_FREIGHT_BOOKING_NOT_FOUND",
}


def lookup(collection, row_id):
    """Resolve a stored row or raise that collection's not-found code."""
    table = getattr(db, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(_COLLECTION_ERRORS[collection])
    return row


def lookup_fk(payload, field, collection):
    """Resolve a body foreign key when present; absent keys fall to rank 5."""
    if field not in payload or payload[field] is None:
        return None
    return lookup(collection, payload[field])


# --------------------------------------------------------------------------
# Rank 5 — ERR_INVALID_REQUEST
# --------------------------------------------------------------------------
def _present(payload, field):
    return field in payload and payload[field] is not None


def req_str(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST")
    return value


def opt_str(payload, field, default=None):
    if not _present(payload, field):
        return default
    return req_str(payload, field)


def _to_decimal(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return D(value)
        except (InvalidOperation, ValueError):
            return None
    return None


def req_num(payload, field, minimum=None, maximum=None, exclusive_min=False):
    value = _to_decimal(payload.get(field))
    if value is None:
        fail("ERR_INVALID_REQUEST")
    if minimum is not None:
        if exclusive_min and value <= D(minimum):
            fail("ERR_INVALID_REQUEST")
        if not exclusive_min and value < D(minimum):
            fail("ERR_INVALID_REQUEST")
    if maximum is not None and value > D(maximum):
        fail("ERR_INVALID_REQUEST")
    return value


def opt_num(payload, field, default=None, minimum=None, exclusive_min=False):
    if not _present(payload, field):
        return default
    return req_num(payload, field, minimum=minimum, exclusive_min=exclusive_min)


def req_int(payload, field, minimum=None, exclusive_min=False):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            fail("ERR_INVALID_REQUEST")
    if minimum is not None:
        if exclusive_min and value <= minimum:
            fail("ERR_INVALID_REQUEST")
        if not exclusive_min and value < minimum:
            fail("ERR_INVALID_REQUEST")
    return value


def req_enum(payload, field, allowed):
    value = payload.get(field)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST")
    return value


def opt_enum(payload, field, allowed, default=None):
    if not _present(payload, field):
        return default
    return req_enum(payload, field, allowed)


def opt_bool(payload, field, default=False):
    if not _present(payload, field):
        return default
    value = payload.get(field)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST")
    return value


def req_date(payload, field):
    value = parse_date(payload.get(field))
    if value is None:
        fail("ERR_INVALID_REQUEST")
    return value


def req_ts(payload, field):
    value = parse_ts(payload.get(field))
    if value is None:
        fail("ERR_INVALID_REQUEST")
    return value


def req_month(payload, field):
    value = payload.get(field)
    if not is_futures_month(value):
        fail("ERR_INVALID_REQUEST")
    return value.strip()


def guard_payload(payload):
    if payload.get("__invalid__"):
        fail("ERR_INVALID_REQUEST")
    return payload
