# Request-body schema helpers (validation priority row 4, PRD 2.8).
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST
from timeutil import parse_iso


def bad(message):
    raise ApiError(ERR_INVALID_REQUEST, 400, message)


def get_body(required):
    """Return the JSON object body. For action endpoints (required=False)
    an absent/empty body maps to {}."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            bad("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def check_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            bad("Unknown field: %s" % key)


def require_fields(body, required):
    for field in required:
        if field not in body or body[field] is None:
            bad("Missing required field: %s" % field)


def as_str(value, name):
    if not isinstance(value, str):
        bad("Field %s must be a string" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %s must be an integer" % name)
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field %s must be a number" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        bad("Field %s must be a boolean" % name)
    return value


def as_datetime(value, name):
    if not isinstance(value, str):
        bad("Field %s must be an ISO8601 datetime string" % name)
    try:
        return parse_iso(value)
    except (ValueError, OverflowError):
        bad("Field %s must be an ISO8601 datetime string" % name)


def as_enum(value, name, members):
    if not isinstance(value, str) or value not in members:
        bad("Field %s must be one of %s" % (name, ", ".join(members)))
    return value


def as_int_at_least(value, name, minimum):
    value = as_int(value, name)
    if value < minimum:
        bad("Field %s must be >= %d" % (name, minimum))
    return value


def validate_tiers(value):
    """tiers: non-empty array of {min_qty, unit_price_cents}, strictly
    ascending min_qty, first min_qty exactly FIRST_TIER_MIN_QTY (1)."""
    import constants as C

    if not isinstance(value, list) or len(value) == 0:
        bad("Field tiers must be a non-empty array")
    tiers = []
    prev_min = None
    for entry in value:
        if not isinstance(entry, dict):
            bad("Each tiers entry must be an object")
        for key in entry:
            if key not in ("min_qty", "unit_price_cents"):
                bad("Unknown field in tiers entry: %s" % key)
        if "min_qty" not in entry or entry["min_qty"] is None:
            bad("Each tiers entry requires min_qty")
        if "unit_price_cents" not in entry or entry["unit_price_cents"] is None:
            bad("Each tiers entry requires unit_price_cents")
        min_qty = as_int(entry["min_qty"], "tiers.min_qty")
        price = as_int(entry["unit_price_cents"], "tiers.unit_price_cents")
        if min_qty < 1:
            bad("tiers.min_qty must be >= 1")
        if price < 0:
            bad("tiers.unit_price_cents must be >= 0")
        if prev_min is not None and min_qty <= prev_min:
            bad("tiers must be sorted ascending by min_qty")
        prev_min = min_qty
        tiers.append({"min_qty": min_qty, "unit_price_cents": price})
    if tiers[0]["min_qty"] != C.FIRST_TIER_MIN_QTY:
        bad("First tier min_qty must be exactly %d" % C.FIRST_TIER_MIN_QTY)
    return tiers
