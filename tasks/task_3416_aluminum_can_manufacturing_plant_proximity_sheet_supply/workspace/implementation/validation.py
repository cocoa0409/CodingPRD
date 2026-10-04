"""Request body/query validation helpers (gate 3, ERR_VALIDATION) and parsers."""
import re
from datetime import datetime

from flask import request

from db import parse_ts
from errors import ApiError, ERR_VALIDATION

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def _bad(msg):
    raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1], msg)


def body_json():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        _bad("Request body must be a JSON object.")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        _bad("Field '%s' is required and must be a non-empty string." % name)
    return v


def opt_str(data, name):
    v = data.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or v == "":
        _bad("Field '%s' must be a non-empty string." % name)
    return v


def _range(name, v, gt, gte, lt, lte):
    if gt is not None and not v > gt:
        _bad("Field '%s' must be > %s." % (name, gt))
    if gte is not None and not v >= gte:
        _bad("Field '%s' must be >= %s." % (name, gte))
    if lt is not None and not v < lt:
        _bad("Field '%s' must be < %s." % (name, lt))
    if lte is not None and not v <= lte:
        _bad("Field '%s' must be <= %s." % (name, lte))


def req_int(data, name, minimum=None):
    v = data.get(name)
    if not _is_int(v):
        _bad("Field '%s' is required and must be an integer." % name)
    if minimum is not None and v < minimum:
        _bad("Field '%s' must be >= %s." % (name, minimum))
    return v


def opt_int(data, name, minimum=None):
    v = data.get(name)
    if v is None:
        return None
    if not _is_int(v):
        _bad("Field '%s' must be an integer." % name)
    if minimum is not None and v < minimum:
        _bad("Field '%s' must be >= %s." % (name, minimum))
    return v


def req_num(data, name, gt=None, gte=None, lt=None, lte=None):
    v = data.get(name)
    if not _is_num(v):
        _bad("Field '%s' is required and must be a number." % name)
    _range(name, v, gt, gte, lt, lte)
    return v


def opt_num(data, name, gt=None, gte=None, lt=None, lte=None):
    v = data.get(name)
    if v is None:
        return None
    if not _is_num(v):
        _bad("Field '%s' must be a number." % name)
    _range(name, v, gt, gte, lt, lte)
    return v


def req_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        _bad("Field '%s' is required and must be a boolean." % name)
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if v not in allowed:
        _bad("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return v


def parse_iso_dt(value, field):
    if not isinstance(value, str):
        _bad("Field '%s' must be an ISO-8601 timestamp." % field)
    try:
        return parse_ts(value)
    except Exception:
        _bad("Field '%s' must be an ISO-8601 timestamp." % field)


def parse_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        _bad("Field '%s' must be an ISO date (YYYY-MM-DD)." % field)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        _bad("Field '%s' must be a valid calendar date (YYYY-MM-DD)." % field)
    return value


def parse_period(value, field):
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        _bad("Field '%s' must be a period (YYYY-MM)." % field)
    month = int(value[5:7])
    if month < 1 or month > 12:
        _bad("Field '%s' must be a valid period (YYYY-MM)." % field)
    return value


def pagination_args():
    def _int_arg(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            _bad("Query parameter '%s' must be an integer." % name)
        return v

    limit = _int_arg("limit", 10)
    offset = _int_arg("offset", 0)
    if limit < 1 or limit > 100:
        _bad("Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        _bad("Query parameter 'offset' must be >= 0.")
    return limit, offset
