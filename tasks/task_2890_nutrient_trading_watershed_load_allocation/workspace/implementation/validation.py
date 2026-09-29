"""Request body / query parameter shape validation (priority 4).

Every failure here is ERR_INVALID_REQUEST with HTTP 422.
"""
import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import dec, parse_date, parse_datetime

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------------------
# field specifications
# --------------------------------------------------------------------------
def spec(
    name,
    kind,
    required=True,
    enum=None,
    minimum=None,
    maximum=None,
    min_exclusive=False,
    max_exclusive=False,
    dp=None,
    pattern=None,
    default=MISSING,
):
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "enum": enum,
        "min": None if minimum is None else dec(minimum),
        "max": None if maximum is None else dec(maximum),
        "min_exclusive": min_exclusive,
        "max_exclusive": max_exclusive,
        "dp": dp,
        "pattern": pattern,
        "default": default,
    }


def raw_body():
    """Parse the request body as JSON with exact decimals.  {} when absent."""
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"), parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _check_number(field, value):
    name = field["name"]
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field '%s' must be a number." % name)
    value = dec(value)
    if field["dp"] is not None:
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or -exponent > field["dp"]:
            bad("Field '%s' carries more than %d decimal places." % (name, field["dp"]))
    if field["min"] is not None:
        if field["min_exclusive"] and value <= field["min"]:
            bad("Field '%s' must be strictly greater than %s." % (name, field["min"]))
        if not field["min_exclusive"] and value < field["min"]:
            bad("Field '%s' must be at least %s." % (name, field["min"]))
    if field["max"] is not None:
        if field["max_exclusive"] and value >= field["max"]:
            bad("Field '%s' must be strictly less than %s." % (name, field["max"]))
        if not field["max_exclusive"] and value > field["max"]:
            bad("Field '%s' must be no greater than %s." % (name, field["max"]))
    return value


def _check_int(field, value):
    name = field["name"]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if field["min"] is not None:
        if field["min_exclusive"] and value <= field["min"]:
            bad("Field '%s' must be strictly greater than %s." % (name, field["min"]))
        if not field["min_exclusive"] and value < field["min"]:
            bad("Field '%s' must be at least %s." % (name, field["min"]))
    if field["max"] is not None and value > field["max"]:
        bad("Field '%s' must be no greater than %s." % (name, field["max"]))
    return value


def _check_one(field, value):
    kind = field["kind"]
    name = field["name"]
    if kind == "string" or kind == "id":
        if not isinstance(value, str):
            bad("Field '%s' must be a string." % name)
        if field["pattern"] is not None and not re.match(field["pattern"], value):
            bad("Field '%s' does not match the required format." % name)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            bad("Field '%s' must be a string." % name)
        if value not in field["enum"]:
            bad("Field '%s' must be one of %s." % (name, ", ".join(field["enum"])))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            bad("Field '%s' must be a boolean." % name)
        return value
    if kind == "int":
        return _check_int(field, value)
    if kind == "number":
        return _check_number(field, value)
    if kind == "date":
        if not isinstance(value, str) or parse_date(value) is None:
            bad("Field '%s' must be an ISO calendar date (YYYY-MM-DD)." % name)
        return value
    if kind == "datetime":
        if not isinstance(value, str) or parse_datetime(value) is None:
            bad("Field '%s' must be an ISO 8601 instant." % name)
        return value
    if kind == "string_array":
        if not isinstance(value, list) or len(value) == 0:
            bad("Field '%s' must be a non-empty array." % name)
        for item in value:
            if not isinstance(item, str):
                bad("Field '%s' must contain only strings." % name)
        return list(value)
    bad("Field '%s' is not supported." % name)


def validate_body(fields):
    """Validate the JSON body against `fields`; returns a value dict."""
    body = raw_body()
    allowed = set(f["name"] for f in fields)
    for key in body.keys():
        if key not in allowed:
            bad("Unknown field '%s'." % key)
    out = {}
    for field in fields:
        name = field["name"]
        if name not in body or body[name] is None:
            if name in body and body[name] is None and field["required"]:
                bad("Field '%s' is required." % name)
            if field["required"]:
                bad("Field '%s' is required." % name)
            out[name] = None if field["default"] is MISSING else field["default"]
            continue
        out[name] = _check_one(field, body[name])
    return out


def present(body_keys, name):
    return name in body_keys


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not re.match(r"^-?\d+$", raw_limit.strip()):
            bad("Query parameter 'limit' must be an integer.")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        if not re.match(r"^-?\d+$", raw_offset.strip()):
            bad("Query parameter 'offset' must be an integer.")
        offset = int(raw_offset.strip())
        if offset < 0:
            bad("Query parameter 'offset' may not be negative.")
    return limit, offset


def enum_arg(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def int_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    if not re.match(r"^-?\d+$", value.strip()):
        bad("Query parameter '%s' must be an integer." % name)
    return int(value.strip())


def str_arg(name):
    return request.args.get(name)


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset : offset + limit]
    return window, total
