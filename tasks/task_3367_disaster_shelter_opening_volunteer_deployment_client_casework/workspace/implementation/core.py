"""Shared infrastructure: logical clock, in-memory store, envelope, validation.

The store is plain Python dicts and starts empty on every boot.  No entity is
seeded, preloaded or hardcoded here or anywhere else in the implementation.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from errors import ApiError, ERROR_STATUS

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "value is not an ISO 8601 instant: %r" % (value,))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_instant(moment):
    """ISO 8601 UTC with exactly three fractional digits."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def iso_of(value):
    """Normalise any accepted instant representation to the wire format."""
    return format_instant(parse_instant(value))


class Clock(object):
    def __init__(self):
        self.now = parse_instant(CLOCK_DEFAULT_ISO)

    def set(self, moment):
        self.now = moment

    def iso(self):
        return format_instant(self.now)

    def plus_days(self, days):
        return self.now + timedelta(days=days)

    def plus_minutes(self, minutes):
        return self.now + timedelta(minutes=minutes)


clock = Clock()


def now_dt():
    return clock.now


def now_iso():
    return clock.iso()


def plus_days_iso(days):
    return format_instant(clock.plus_days(days))


def plus_minutes_iso(minutes):
    return format_instant(clock.plus_minutes(minutes))


def round_half_up(value, places=0):
    """Round half away from zero at the requested number of decimal places."""
    dec = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return dec.quantize(quant, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

TABLES = [
    "regions",
    "disaster_relief_operations",
    "shelter_sites",
    "shelter_operations",
    "volunteers",
    "volunteer_deployments",
    "shift_assignments",
    "clients",
    "shelter_registrations",
    "client_cases",
    "referrals",
    "assistance_requests",
    "fund_pools",
    "cost_ledger_entries",
    "blood_drives",
]

db = {name: {} for name in TABLES}
feeding_events = {}  # shelter_operation_id -> [event, ...] (internal)

NOT_FOUND_ERROR = {
    "regions": "ERR_REGION_NOT_FOUND",
    "disaster_relief_operations": "ERR_OPERATION_NOT_FOUND",
    "shelter_sites": "ERR_SHELTER_SITE_NOT_FOUND",
    "shelter_operations": "ERR_SHELTER_OPERATION_NOT_FOUND",
    "volunteers": "ERR_VOLUNTEER_NOT_FOUND",
    "volunteer_deployments": "ERR_DEPLOYMENT_NOT_FOUND",
    "clients": "ERR_CLIENT_NOT_FOUND",
    "client_cases": "ERR_CASE_NOT_FOUND",
    "referrals": "ERR_REFERRAL_NOT_FOUND",
    "fund_pools": "ERR_FUND_POOL_NOT_FOUND",
    "blood_drives": "ERR_BLOOD_DRIVE_NOT_FOUND",
    "shift_assignments": "ERR_INVALID_REQUEST",
    "shelter_registrations": "ERR_INVALID_REQUEST",
    "cost_ledger_entries": "ERR_INVALID_REQUEST",
}


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24].upper()


def base_row():
    stamp = now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


def insert(table, record):
    db[table][record["id"]] = record
    return record


def rows(table):
    return list(db[table].values())


def find(table, rid):
    return db[table].get(rid)


def must_get(table, rid):
    record = db[table].get(rid)
    if record is None:
        raise ApiError(NOT_FOUND_ERROR.get(table, "ERR_INVALID_REQUEST"), 404,
                       "%s %r does not exist" % (table, rid))
    return record


def touch(record):
    """Every mutation refreshes updated_at and bumps version by exactly one."""
    record["version"] = int(record.get("version", 1)) + 1
    record["updated_at"] = now_iso()
    return record


def apply(record, changes):
    """Write derived values; a changed value is itself a mutation."""
    dirty = False
    for key, value in changes.items():
        if record.get(key) != value:
            record[key] = value
            dirty = True
    if dirty:
        touch(record)
    return dirty


def serialize(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_many(records):
    return [serialize(r) for r in records]


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def ok_object(payload, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": payload if payload is not None else {},
    }
    return jsonify(body), status


def ok_array(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, http_status):
    return jsonify(error_body(error_id, message)), http_status


def _int_param(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def pagination():
    limit = _int_param(request.args.get("limit"), 10)
    offset = _int_param(request.args.get("offset"), 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(records, limit=None, offset=None):
    if limit is None or offset is None:
        limit, offset = pagination()
    ordered = sorted(records, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_array(serialize_many(window), total, limit, offset)


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------


def read_json():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return body


def _is_instant(value):
    if not isinstance(value, str):
        return False
    try:
        parse_instant(value)
        return True
    except ApiError:
        return False


def _check_type(field, value, expected):
    if expected is str:
        ok = isinstance(value, str)
    elif expected is bool:
        ok = isinstance(value, bool)
    elif expected is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif expected is list:
        ok = isinstance(value, list)
    elif expected == "instant":
        ok = _is_instant(value)
    else:
        ok = True
    if not ok:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r has the wrong type" % (field,))


def validate_body(body, required=None, optional=None):
    """Required fields present, declared types honoured, no undeclared fields."""
    required = required or {}
    optional = optional or {}
    for key in body:
        if key not in required and key not in optional:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "undeclared field %r" % (key,))
    for key, expected in required.items():
        if key not in body or body[key] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "missing required field %r" % (key,))
        _check_type(key, body[key], expected)
    for key, expected in optional.items():
        if key in body and body[key] is not None:
            _check_type(key, body[key], expected)
    return body


def validate_enum(field, value, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r must be one of %s" % (field, ", ".join(allowed)))
    return value


# --------------------------------------------------------------------------
# Authentication / RBAC
# --------------------------------------------------------------------------


def authenticate(allowed_roles, headers_optional=False):
    """X-User-ID / X-User-Role presence then role authorisation.

    headers_optional is used only by the logical-clock administration endpoint,
    which PRD 2.1 exempts from the header-presence requirement.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    user_id = user_id.strip() if isinstance(user_id, str) else user_id
    role = role.strip() if isinstance(role, str) else role
    if headers_optional and not user_id and not role:
        return None, None
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH_HEADER", 401,
                       "X-User-ID and X-User-Role headers are required")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "role %r may not perform this operation" % (role,))
    return user_id, role
