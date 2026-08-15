"""Shared helpers: timestamps, request body validation, Decimal coercion.

Precision conventions (PRD §2.9): SOC percentages 1dp; voltages and
declared_weight_kg 2dp; computed energy/heat/scores 2dp HALF_UP; carrier
charge integer cents HALF_UP."""

import math
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import err_invalid_request, err_invalid_enum

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime into an aware UTC datetime. 400 on failure."""
    if not isinstance(value, str):
        raise err_invalid_request("%s must be an ISO 8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except (ValueError, TypeError):
        raise err_invalid_request("%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_body(required=False):
    """Return the JSON request body as a dict. Empty body -> {} unless required."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise err_invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise err_invalid_request("Missing required field: %s" % name)
    return body[name]


def opt_field(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err_invalid_request("%s must be a non-empty string" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request("%s must be an integer" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err_invalid_request("%s must be a boolean" % field)
    return value


def as_decimal(value, field):
    """Accept a JSON number (not bool, not NaN/inf) and return Decimal."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err_invalid_request("%s must be a number" % field)
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise err_invalid_request("%s must be a number" % field)
    if d.is_nan() or d.is_infinite():
        raise err_invalid_request("%s must be a finite number" % field)
    return d


def as_enum(value, field, allowed):
    if not isinstance(value, str):
        raise err_invalid_request("%s must be a string" % field)
    if value not in allowed:
        raise err_invalid_enum(
            "%s must be one of {%s}" % (field, ", ".join(sorted(allowed)))
        )
    return value


def as_enum_list(value, field, allowed):
    if not isinstance(value, list):
        raise err_invalid_request("%s must be a list" % field)
    out = []
    for v in value:
        if not isinstance(v, str):
            raise err_invalid_request("%s must be a list of strings" % field)
        if v not in allowed:
            raise err_invalid_enum(
                "%s entries must be one of {%s}" % (field, ", ".join(sorted(allowed)))
            )
        out.append(v)
    return out


def round_half_up(d, places):
    q = Decimal(1).scaleb(-places)  # 10^-places
    return d.quantize(q, rounding=ROUND_HALF_UP)


def num(d, places=None):
    """Serialize a Decimal/int to a JSON number, rounding HALF_UP when asked."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    if places is not None:
        d = round_half_up(d, places)
    f = float(d)
    return f


def clamp(d, lo, hi):
    return max(lo, min(hi, d))
