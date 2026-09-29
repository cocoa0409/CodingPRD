"""Request-shape validation (PRD 2.9 step 4) and pagination (step 5)."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_ts
from errors import ApiError, fail

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body_json():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(body, name, required):
    if name not in body or body[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return False
    return True


def field_str(body, name, required=True, min_len=1, max_len=None, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def field_int(body, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return value


def field_bool(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def field_decimal(body, name, required=True, minimum=None, maximum=None,
                  exclusive_min=None, exclusive_max=None, scale=None, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    # A scaled decimal may arrive as a JSON number or as its exact decimal
    # string form; the PRD fixes the scale of each quantity but never the wire
    # representation, so both spellings of the same value are accepted.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("Field '%s' must be a number." % name)
    try:
        if isinstance(value, float):
            dec = Decimal(repr(value))
        elif isinstance(value, str):
            dec = Decimal(value.strip())
        else:
            dec = Decimal(value)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % name)
    if not dec.is_finite():
        bad("Field '%s' must be a number." % name)
    if scale is not None:
        exponent = -dec.as_tuple().exponent
        if exponent > scale:
            bad("Field '%s' allows at most %d decimal places." % (name, scale))
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be at most %s." % (name, maximum))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    if exclusive_max is not None and dec >= Decimal(str(exclusive_max)):
        bad("Field '%s' must be less than %s." % (name, exclusive_max))
    return dec


def field_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def field_date(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        bad("Field '%s' must be a YYYY-MM-DD date." % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        bad("Field '%s' must be a valid calendar date." % name)
    return value


def field_ts(body, name, required=True, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, str) or not TS_PATTERN.match(value):
        bad("Field '%s' must be an ISO 8601 UTC instant ending in Z." % name)
    try:
        return parse_ts(value)
    except Exception:
        bad("Field '%s' must be a valid ISO 8601 UTC instant." % name)


def field_id(body, name, required=True, default=None):
    return field_str(body, name, required=required, min_len=1, default=default)


def field_array(body, name, required=True, min_len=1, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must contain at least %d item(s)." % (name, min_len))
    return value


def field_object_array(body, name, required=True, min_len=1):
    items = field_array(body, name, required=required, min_len=min_len)
    if items is None:
        return None
    for item in items:
        if not isinstance(item, dict):
            bad("Every item of '%s' must be an object." % name)
    return items


# ---------------------------------------------------------------- pagination

def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if str(limit) != limit_raw.strip():
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if str(offset) != offset_raw.strip():
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# ------------------------------------------------------------- query filters

def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    bad("Query parameter '%s' must be true or false." % name)


def query_str(name):
    return request.args.get(name)


def query_date(name):
    value = request.args.get(name)
    if value is None:
        return None
    if not DATE_PATTERN.match(value):
        bad("Query parameter '%s' must be a YYYY-MM-DD date." % name)
    return value
