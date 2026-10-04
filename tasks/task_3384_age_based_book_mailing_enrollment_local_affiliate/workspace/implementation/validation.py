"""Auth extraction, body well-formedness checks and scalar parsers."""

import re
from datetime import datetime, date, timezone

from flask import request

from errors import ApiError

ALL_ROLES = (
    "PlatformAdmin",
    "StateProgramOfficer",
    "AffiliateCoordinator",
    "AdvisoryCommitteeMember",
    "PublisherOps",
    "MailOps",
)

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_PREFIX_RE = re.compile(r"^[A-Z0-9]{2,5}$")

ADDRESS_KEYS = ("line1", "city", "region", "postal_code", "country")


def _bad(message):
    raise ApiError(400, "ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------------------
# Auth (validation priority 1 and 2)
# --------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError(401, "ERR_UNAUTHENTICATED",
                       "Missing or unrecognized X-User-ID / X-User-Role header")
    return uid, role


def require_roles(*roles):
    uid, role = auth()
    if role not in roles:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Caller role is not authorized for this endpoint")
    return uid, role


# --------------------------------------------------------------------------
# Body well-formedness (validation priority 4)
# --------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def check_allowed(data, allowed):
    for key in data:
        if key not in allowed:
            _bad("Unknown, system or computed field supplied: %s" % key)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_string(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        _bad("Field '%s' is required and must be a non-empty string" % name)
    return v


def opt_string(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], str):
        _bad("Field '%s' must be a string" % name)
    return data[name]


def req_int(data, name, lo=None, hi=None):
    if name not in data or data[name] is None:
        _bad("Field '%s' is required and must be an integer" % name)
    v = data[name]
    if not _is_int(v):
        _bad("Field '%s' must be an integer" % name)
    if lo is not None and v < lo:
        _bad("Field '%s' must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        _bad("Field '%s' must be <= %d" % (name, hi))
    return v


def opt_int(data, name, default=None, lo=None, hi=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not _is_int(v):
        _bad("Field '%s' must be an integer" % name)
    if lo is not None and v < lo:
        _bad("Field '%s' must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        _bad("Field '%s' must be <= %d" % (name, hi))
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], bool):
        _bad("Field '%s' must be a boolean" % name)
    return data[name]


def check_month(v):
    if not isinstance(v, str) or not _MONTH_RE.match(v):
        _bad("Month values must match YYYY-MM")
    mm = int(v[5:7])
    if mm < 1 or mm > 12:
        _bad("Month values must match YYYY-MM with month 01-12")
    return v


def req_month(data, name):
    return check_month(req_string(data, name))


def parse_dt_raw(raw):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    if not isinstance(raw, str) or not raw.strip():
        _bad("Expected an ISO8601 datetime string")
    t = raw.strip()
    if t[-1] in ("Z", "z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _bad("Malformed ISO8601 datetime: %r" % raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(data, name):
    """Returns (raw_string, parsed_utc_datetime)."""
    raw = req_string(data, name)
    return raw, parse_dt_raw(raw)


def parse_date_value(raw):
    """Accepts an ISO8601 date (YYYY-MM-DD) or full datetime; returns a date."""
    if not isinstance(raw, str) or not raw.strip():
        _bad("Expected an ISO8601 date string")
    t = raw.strip()
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    return parse_dt_raw(raw).date()


def req_address(data, name):
    v = data.get(name)
    if not isinstance(v, dict):
        _bad("Field '%s' is required and must be an object" % name)
    for key in v:
        if key not in ADDRESS_KEYS:
            _bad("Unknown address field: %s" % key)
    for key in ADDRESS_KEYS:
        if key not in v or not isinstance(v[key], str):
            _bad("Address field '%s' is required and must be a string" % key)
    if v["postal_code"].strip() == "":
        _bad("Address field 'postal_code' must be non-empty")
    return {key: v[key] for key in ADDRESS_KEYS}


def req_prefixes(data, name):
    v = data.get(name)
    if not isinstance(v, list) or len(v) == 0:
        _bad("Field '%s' must be a non-empty array" % name)
    for p in v:
        if not isinstance(p, str) or not _PREFIX_RE.match(p):
            _bad("postal_prefixes entries must be 2-5 uppercase alphanumeric characters")
    return list(v)


# --------------------------------------------------------------------------
# Pagination query parameters (limit 1..100 default 10, offset >= 0 default 0)
# --------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset must be >= 0")
    return limit, offset
