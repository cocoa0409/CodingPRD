"""Shared helpers: response envelope, auth, body parsing, field validators,
datetime parsing, pagination. All structural names come from the PRD/scaffold:
headers X-User-ID / X-User-Role; envelope meta/api_request_id/
api_request_timestamp/response_type/data; error data.error_id/data.message;
pagination limit/offset/total_count/has_more (default 10, min 1, max 100).
"""
import secrets
import string
from datetime import datetime, timezone

from flask import request, jsonify

from db import get_clock
from errors import (
    ApiError, raise_err, E_MISSING_HEADERS, E_FORBIDDEN, E_INVALID_REQUEST,
)

DECLARED_ROLES = {
    "PlatformAdmin", "AffiliateStaff", "Assessor", "Homeowner",
    "Volunteer", "TradePartner", "SponsorRep", "Anonymous", "Any",
}

TRADE_VALUES = ("NONE", "CARPENTRY", "ELECTRICAL", "PLUMBING", "ROOFING", "HVAC")
CONTRACTOR_TRADES = ("CARPENTRY", "ELECTRICAL", "PLUMBING", "ROOFING", "HVAC")


# ---------------------------------------------------------------- envelope ---
def now_iso():
    """Wall-clock UTC timestamp with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _request_id():
    return "req_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(24)
    )


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok_obj(data, code=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), code


def ok_list(items, total, limit, offset, code=200):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return jsonify({
        "meta": m,
        "response_type": "array",
        "data": items,
    }), code


def error_envelope(error_id, status, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status


# -------------------------------------------------------------------- auth ---
def require_roles(*allowed):
    """Tier 1 + 2: header presence/role validity, then endpoint authorization.
    'Any' authorizes every declared role except Anonymous."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in DECLARED_ROLES:
        raise_err(E_MISSING_HEADERS, 400,
                  "X-User-ID and X-User-Role headers are required and the role "
                  "must be a declared role")
    granted = False
    for a in allowed:
        if a == "Any":
            if role != "Anonymous":
                granted = True
        elif role == a:
            granted = True
    if not granted:
        raise_err(E_FORBIDDEN, 403,
                  "role %s is not authorized for this endpoint" % role)
    return uid, role


# -------------------------------------------------------------------- body ---
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(E_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def _bad(field, msg):
    raise_err(E_INVALID_REQUEST, 400, "%s: %s" % (field, msg))


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or v == "":
        _bad(k, "required non-empty string")
    return v


def opt_str(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    if not isinstance(b[k], str):
        _bad(k, "must be a string")
    return b[k]


def req_int(b, k, lo=None, hi=None):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(k, "required integer")
    if lo is not None and v < lo:
        _bad(k, "must be >= %d" % lo)
    if hi is not None and v > hi:
        _bad(k, "must be <= %d" % hi)
    return v


def opt_int(b, k, default=None, lo=None, hi=None):
    if k not in b or b[k] is None:
        return default
    return req_int(b, k, lo, hi)


def req_bool(b, k):
    v = b.get(k)
    if not isinstance(v, bool):
        _bad(k, "required boolean")
    return v


def opt_bool(b, k, default=False):
    if k not in b or b[k] is None:
        return default
    return req_bool(b, k)


def req_enum(b, k, values):
    v = b.get(k)
    if not isinstance(v, str) or v not in values:
        _bad(k, "must be one of %s" % ", ".join(values))
    return v


def opt_enum(b, k, values, default=None):
    if k not in b or b[k] is None:
        return default
    return req_enum(b, k, values)


def req_array(b, k, non_empty=False):
    v = b.get(k)
    if not isinstance(v, list):
        _bad(k, "required array")
    if non_empty and len(v) == 0:
        _bad(k, "must be a non-empty array")
    return v


def opt_array(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    return req_array(b, k)


def req_number(b, k):
    """A JSON number (int or float, not bool). Returns the raw value."""
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(k, "required number")
    return v


# ---------------------------------------------------------------- datetime ---
def parse_dt(value):
    """Parse an ISO-8601 date or datetime into an aware UTC datetime.
    Returns None when unparseable. Naive inputs are treated as UTC."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    dt = parse_dt(value)
    return dt.date() if dt is not None else None


def req_dt(b, k):
    """Require a parseable ISO-8601 date/datetime; returns the raw string."""
    v = b.get(k)
    if parse_dt(v) is None:
        _bad(k, "required ISO-8601 date/datetime")
    return v


def opt_dt(b, k, default=None):
    if k not in b or b[k] is None:
        return default
    return req_dt(b, k)


def clock_dt():
    return parse_dt(get_clock())


def clock_date():
    dt = clock_dt()
    return dt.date() if dt is not None else None


# -------------------------------------------------------------- pagination ---
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        _bad("limit", "must be an integer")
    try:
        offset = 0 if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        _bad("offset", "must be an integer")
    if limit < 1 or limit > 100:
        _bad("limit", "must be between 1 and 100")
    if offset < 0:
        _bad("offset", "must be >= 0")
    return limit, offset


def sorted_page(records, limit, offset):
    """Default sort: created_at ascending (insertion order breaks ties)."""
    recs = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    return recs[offset:offset + limit], len(recs)


def list_response(records, serializer):
    limit, offset = pagination()
    page, total = sorted_page(records, limit, offset)
    return ok_list([serializer(r) for r in page], total, limit, offset)


# --------------------------------------------------------------- existence ---
def get_or_404(store, rid, error_id):
    from db import STORES
    rec = STORES[store].get(rid)
    if rec is None:
        raise_err(error_id, 404, "resource %s not found" % rid)
    return rec
