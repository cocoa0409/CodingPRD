"""Request body shape validation. Failures are ERR_INVALID_REQUEST (400),
evaluated independently of the validation priority ladder (PRD section 2.8)."""
import re
from datetime import date as _date

from flask import request

import clock
from errors import invalid_request as _invalid

METHODS = {"CARD", "ECHECK", "WALLET"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _invalid("Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        _invalid("Missing required field: %s" % name)
    return data[name]


def opt_field(data, name):
    """Optional field; an explicit JSON null is treated as omitted."""
    return data.get(name)


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        _invalid("Field %s must be a non-empty string" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid("Field %s must be an integer" % name)
    return value


def as_positive_int(value, name):
    v = as_int(value, name)
    if v <= 0:
        _invalid("Field %s must be a positive integer" % name)
    return v


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        _invalid("Field %s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def as_instant(value, name):
    """Parse an ISO 8601 instant; returns (datetime, raw_string)."""
    if not isinstance(value, str):
        _invalid("Field %s must be an ISO 8601 timestamp string" % name)
    try:
        return clock.parse_instant(value), value
    except ValueError:
        _invalid("Field %s is not a valid ISO 8601 timestamp" % name)


def as_date(value, name):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        _invalid("Field %s must be a YYYY-MM-DD date string" % name)
    try:
        _date.fromisoformat(value)
    except ValueError:
        _invalid("Field %s is not a valid calendar date" % name)
    return value


def as_month(value, name):
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        _invalid("Field %s must be a YYYY-MM month string" % name)
    mm = int(value[5:7])
    if mm < 1 or mm > 12:
        _invalid("Field %s is not a valid month" % name)
    return value


def as_method_set(value, name):
    if not isinstance(value, list) or not value:
        _invalid("Field %s must be a non-empty array of payment methods" % name)
    seen = set()
    for m in value:
        if not isinstance(m, str) or m not in METHODS:
            _invalid("Field %s entries must be drawn from CARD, ECHECK, WALLET" % name)
        seen.add(m)
    return [m for m in value]
