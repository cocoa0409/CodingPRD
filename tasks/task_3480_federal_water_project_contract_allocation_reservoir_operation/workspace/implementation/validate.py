"""Request shape validation helpers (PRD section 2.9 step 3).

Shape failures are ERR_INVALID_REQUEST (400): missing required fields, bad
types, bad enum members, bad ranges. Positive-quantity semantics for
ordered_af / quantity_af / claimed_impact_af / delivered_af are deliberately
NOT here — those are ERR_INVALID_QUANTITY at business-constraint priority 8.
"""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_dt

PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return data


def required(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: " + name)
    return body[name]


def as_str(value, name):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, name + " must be a string")
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, name + " must be an integer")
    return value


def as_int_range(value, name, lo, hi=None):
    value = as_int(value, name)
    if value < lo or (hi is not None and value > hi):
        bound = (">= " + str(lo)) if hi is None else (
            "between " + str(lo) + " and " + str(hi))
        raise ApiError("ERR_INVALID_REQUEST", 400, name + " must be " + bound)
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, name + " must be a number")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ApiError("ERR_INVALID_REQUEST", 400, name + " must be a number")


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       name + " must be one of: " + ", ".join(allowed))
    return value


def as_datetime(value, name):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       name + " must be an ISO8601 timestamp string")
    try:
        return parse_dt(value)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       name + " must be a valid ISO8601 timestamp")


def as_period_month(value, name="period_month"):
    if not isinstance(value, str) or not PERIOD_MONTH_RE.match(value):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       name + " must match the 'YYYY-MM' format")
    return value
