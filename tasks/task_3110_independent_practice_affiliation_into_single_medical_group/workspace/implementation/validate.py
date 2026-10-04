"""Shared request-body validation helpers."""

import re
from datetime import date

from flask import request

from errors import err_invalid

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid("request body must be a JSON object")
    return data


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid(f"{field} must be a non-empty string")
    return v


def optional_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise err_invalid(f"{field} must be a string")
    return v


def require_int(data, field, min_value=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid(f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise err_invalid(f"{field} must be >= {min_value}")
    return v


def optional_int(data, field, default=None, min_value=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid(f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise err_invalid(f"{field} must be >= {min_value}")
    return v


def require_number(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid(f"{field} must be a number")
    return v


def optional_number(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid(f"{field} must be a number")
    return v


def require_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise err_invalid(f"{field} must be a boolean")
    return v


def require_enum(data, field, values):
    v = data.get(field)
    if not isinstance(v, str) or v not in values:
        raise err_invalid(f"{field} must be one of {sorted(values)}")
    return v


def require_date(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise err_invalid(f"{field} must be ISO YYYY-MM-DD")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise err_invalid(f"{field} must be a valid calendar date")


def optional_date(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return require_date(data, field)


def require_period(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not PERIOD_RE.match(v):
        raise err_invalid(f"{field} must match YYYY-MM")
    try:
        y, m = v.split("-")
        if not (1 <= int(m) <= 12):
            raise ValueError
    except ValueError:
        raise err_invalid(f"{field} must match YYYY-MM")
    return v


def parse_iso_instant(s):
    """Parse an ISO-8601 instant; returns an aware datetime in UTC."""
    from datetime import datetime, timezone

    if not isinstance(s, str):
        raise err_invalid("to_iso8601 must be a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise err_invalid("to_iso8601 must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
