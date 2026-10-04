"""Request parsing, body-shape validation, pagination, and the FFY rule."""
import math

from flask import request

from db import STORE, parse_iso
from errors import err


def _bad(message):
    return err("ERR_INVALID_REQUEST", message)


def get_body():
    """Return the JSON request body as a dict; absent body -> {}.
    A non-object JSON body is malformed."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _bad("Request body must be a JSON object")
    return data


def req_field(body, field):
    if field not in body or body[field] is None:
        raise _bad(f"Missing required field: {field}")
    return body[field]


def as_str(value, field):
    if not isinstance(value, str):
        raise _bad(f"Field {field} must be a string")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise _bad(f"Field {field} must be a boolean")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(f"Field {field} must be an integer")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(f"Field {field} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise _bad(f"Field {field} must be a finite number")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise _bad(f"Field {field} must be one of {', '.join(allowed)}")
    return value


def as_datetime(value, field):
    """Validate an ISO 8601 datetime string; returns the parsed instant.
    The raw string is what gets stored/returned (PRD §2.4)."""
    if not isinstance(value, str):
        raise _bad(f"Field {field} must be an ISO 8601 datetime string")
    try:
        return parse_iso(value)
    except Exception:
        raise _bad(f"Field {field} must be an ISO 8601 datetime string")


def pagination_params():
    """limit defaults to 10, clamped to [1, 100]; offset defaults to 0,
    clamped to >= 0 (PRD §2.3 / scaffold pagination_defaults)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise _bad("limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise _bad("offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items):
    """Slice an already-sorted list per the pagination parameters."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return page, total, limit, offset


def query_int(name):
    """Parse an optional integer query filter; absent -> None."""
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise _bad(f"{name} must be an integer")


def ffy_of(dt):
    """Federal fiscal year of an instant: Oct-Dec of calendar year Y belongs
    to FFY Y+1; Jan-Sep of Y belongs to FFY Y (PRD §2.4)."""
    return dt.year + 1 if dt.month >= 10 else dt.year


def resolve_body_fk(store_key, value, field):
    """Body foreign-key resolution: a present FK value must resolve to an
    existing resource, else ERR_NOT_FOUND (PRD §2.9)."""
    target = None
    if isinstance(value, str):
        target = STORE[store_key].get(value)
    if target is None:
        raise err("ERR_NOT_FOUND", f"{field} does not resolve to an existing resource")
    return target
