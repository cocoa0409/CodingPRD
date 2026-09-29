"""Rung 4 of the ladder: schema validity of the request body.

Numbers arrive as Decimal (the body is parsed with parse_float=Decimal) so a
client's literal is never dragged through binary floating point before we
quantize it to the field's declared precision.
"""
import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import parse_dt, rhu

_SITE_CODE_RE = re.compile(r"^[A-Z0-9]+$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """The request body as a dict. Absent or empty bodies read as {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(body, field, required, default):
    if field not in body or body[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return False, default
    return True, None


def s_str(body, field, min_len=1, max_len=None, required=True, default=None):
    ok, fallback = _present(body, field, required, default)
    if not ok:
        return fallback
    value = body[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if len(value.strip()) < min_len:
        bad("Field '%s' must be at least %d characters and not blank." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (field, max_len))
    return value


def s_code(body, field, min_len, max_len, required=True, upper_alnum=False):
    value = s_str(body, field, min_len=min_len, max_len=max_len, required=required)
    if value is None:
        return None
    if len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (field, min_len))
    if upper_alnum and not _SITE_CODE_RE.match(value):
        bad("Field '%s' accepts uppercase A-Z and digits only." % field)
    return value


def s_id(body, field, required=True):
    ok, fallback = _present(body, field, required, None)
    if not ok:
        return fallback
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty identifier string." % field)
    return value


def s_num(body, field, places, required=True, default=None,
          gt=None, ge=None, le=None):
    ok, fallback = _present(body, field, required, default)
    if not ok:
        return fallback
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field '%s' must be a number." % field)
    try:
        value = Decimal(value)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % field)
    if not value.is_finite():
        bad("Field '%s' must be a finite number." % field)
    if gt is not None and value <= Decimal(str(gt)):
        bad("Field '%s' must be greater than %s." % (field, gt))
    if ge is not None and value < Decimal(str(ge)):
        bad("Field '%s' must be at least %s." % (field, ge))
    if le is not None and value > Decimal(str(le)):
        bad("Field '%s' must be at most %s." % (field, le))
    return rhu(value, places)


def s_int(body, field, required=True, default=None, ge=None, le=None):
    ok, fallback = _present(body, field, required, default)
    if not ok:
        return fallback
    value = body[field]
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % field)
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            bad("Field '%s' must be an integer." % field)
        value = int(value)
    if not isinstance(value, int):
        bad("Field '%s' must be an integer." % field)
    if ge is not None and value < ge:
        bad("Field '%s' must be at least %s." % (field, ge))
    if le is not None and value > le:
        bad("Field '%s' must be at most %s." % (field, le))
    return value


def s_bool(body, field, required=True, default=None):
    ok, fallback = _present(body, field, required, default)
    if not ok:
        return fallback
    value = body[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def s_enum(body, field, values, required=True, default=None):
    ok, fallback = _present(body, field, required, default)
    if not ok:
        return fallback
    value = body[field]
    if not isinstance(value, str) or value not in values:
        bad("Field '%s' must be one of %s." % (field, ", ".join(values)))
    return value


def s_dt(body, field, required=True, default=None):
    ok, fallback = _present(body, field, required, default)
    if not ok:
        return fallback
    value = body[field]
    try:
        return parse_dt(value)
    except (ValueError, TypeError):
        bad("Field '%s' must be an ISO 8601 instant." % field)


def s_month(body, field, required=True):
    ok, fallback = _present(body, field, required, None)
    if not ok:
        return fallback
    value = body[field]
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        bad("Field '%s' must be exactly YYYY-MM with a month between 01 and 12." % field)
    return value


def query_enum(name, values):
    """A list filter drawn from a closed vocabulary. Unknown values match nothing."""
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in values:
        return "\x00no-such-value"
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
