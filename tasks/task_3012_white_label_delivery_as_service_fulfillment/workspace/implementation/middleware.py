"""Auth (PRD section 2.1), payload validation, pagination, datetime helpers."""
from datetime import datetime, timezone

from flask import request

import errors

ROLES = {"PlatformAdmin", "Merchant", "Courier", "SupportAgent"}


def get_context():
    """Layer 1: X-User-ID and X-User-Role present, role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise errors.missing_context()
    return uid, role


def require_role(*roles):
    """Layers 1-2: auth context, then role authorization for this endpoint."""
    uid, role = get_context()
    if role not in roles:
        raise errors.unauthorized_role()
    return uid, role


def body():
    if not request.is_json:
        raise errors.bad_request("Request body must be JSON")
    b = request.get_json(silent=True)
    if b is None or not isinstance(b, dict):
        raise errors.bad_request("Request body must be a JSON object")
    return b


def req_field(b, name):
    if name not in b or b[name] is None:
        raise errors.bad_request("Missing required field: %s" % name)
    return b[name]


def opt_field(b, name, default=None):
    v = b.get(name, default)
    return default if v is None else v


def req_str(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, str):
        raise errors.bad_request("Field %s must be a string" % name)
    return v


def opt_str(b, name, default=None):
    v = opt_field(b, name, default)
    if v is not default and (isinstance(v, bool) or not isinstance(v, str)):
        raise errors.bad_request("Field %s must be a string" % name)
    return v


def req_int(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.bad_request("Field %s must be an integer" % name)
    return v


def opt_int(b, name, default=None):
    v = opt_field(b, name, default)
    if v is not default and (isinstance(v, bool) or not isinstance(v, int)):
        raise errors.bad_request("Field %s must be an integer" % name)
    return v


def req_num(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.bad_request("Field %s must be a number" % name)
    return v


def opt_bool(b, name, default=None):
    v = opt_field(b, name, default)
    if v is not default and not isinstance(v, bool):
        raise errors.bad_request("Field %s must be a boolean" % name)
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        raise errors.bad_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(b, name, allowed, default=None):
    v = opt_field(b, name, default)
    if v is default:
        return v
    if isinstance(v, bool) or not isinstance(v, str) or v not in allowed:
        raise errors.bad_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def parse_dt(v, field="datetime"):
    if isinstance(v, bool) or not isinstance(v, str):
        raise errors.bad_request("Field %s must be an ISO 8601 datetime string" % field)
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.bad_request("Field %s must be an ISO 8601 datetime string" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, name):
    return parse_dt(req_field(b, name), name)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def pagination_args():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise errors.bad_request("limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise errors.bad_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.bad_request("offset must be >= 0")
    return limit, offset
