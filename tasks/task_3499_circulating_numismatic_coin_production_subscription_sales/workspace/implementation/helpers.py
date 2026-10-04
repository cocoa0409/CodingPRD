"""Response envelope, authentication, pagination, and payload validation.

All structural names come from the scaffold: envelope field names
(meta/api_request_id/api_request_timestamp/response_type/data), pagination
(limit/offset/total_count/has_more), and the twelve declared roles.
"""
import secrets
from decimal import Decimal

from flask import jsonify, request

import store
from errors import ApiError

ROLES = {
    "Anonymous", "PlatformAdmin", "FedLiaison", "ProcurementOfficer",
    "ProductionPlanner", "QualityInspector", "DestructionCertifier",
    "ProgramManager", "MintDirector", "FinanceOfficer", "Collector",
    "BullionDealer",
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def bad_request(message):
    err("ERR_INVALID_REQUEST", 400, message)


def not_found(message="Resource not found"):
    err("ERR_NOT_FOUND", 404, message)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def envelope(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": store.render_system_ts(store.now_dt()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_envelope(api_err):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": store.render_system_ts(store.now_dt()),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


# ---------------------------------------------------------------------------
# Auth (rung 1 and rung 2 of the validation ladder)
# ---------------------------------------------------------------------------
def auth(*allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401,
            "X-User-ID and X-User-Role headers are required and the role must be declared")
    if allowed_roles and role not in allowed_roles:
        err("ERR_UNAUTHORIZED_ROLE", 403,
            "Role %s is not authorized for this endpoint" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Pagination (limit/offset with scaffold defaults 10/0, bounds [1,100])
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit, 10)
    except (ValueError, TypeError):
        bad_request("limit must be an integer")
    if limit < 1 or limit > 100:
        bad_request("limit must be between 1 and 100")
    try:
        offset = int(raw_offset, 10)
    except (ValueError, TypeError):
        bad_request("offset must be an integer")
    if offset < 0:
        bad_request("offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def list_response(items, serializer):
    limit, offset = pagination_params()
    ordered = store.sort_created(items)
    page, meta = paginate(ordered, limit, offset)
    return envelope([serializer(e) for e in page], response_type="array",
                    status=200, pagination=meta)


# ---------------------------------------------------------------------------
# Payload shape validation (rung 9)
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        bad_request("Request body must be a JSON object")
    return b


def no_undeclared(b, allowed):
    for k in b.keys():
        if k not in allowed:
            bad_request("Undeclared or read-only field in payload: %s" % k)


def _present(b, name):
    return name in b and b[name] is not None


def need_str(b, name):
    if not _present(b, name):
        bad_request("Missing required field: %s" % name)
    if not isinstance(b[name], str):
        bad_request("Field %s must be a string" % name)
    return b[name]


def opt_str(b, name):
    if not _present(b, name):
        return None
    if not isinstance(b[name], str):
        bad_request("Field %s must be a string" % name)
    return b[name]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def need_int(b, name):
    if not _present(b, name):
        bad_request("Missing required field: %s" % name)
    if not _is_int(b[name]):
        bad_request("Field %s must be an integer" % name)
    return b[name]


def opt_int(b, name):
    if not _present(b, name):
        return None
    if not _is_int(b[name]):
        bad_request("Field %s must be an integer" % name)
    return b[name]


def need_num(b, name):
    """A JSON number (int or float, not bool), returned as Decimal."""
    if not _present(b, name):
        bad_request("Missing required field: %s" % name)
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request("Field %s must be a number" % name)
    return Decimal(str(v))


def need_enum(b, name, choices):
    v = need_str(b, name)
    if v not in choices:
        bad_request("Field %s must be one of %s" % (name, sorted(choices)))
    return v


def opt_bool(b, name, default=None):
    if not _present(b, name):
        return default
    if not isinstance(b[name], bool):
        bad_request("Field %s must be a boolean" % name)
    return b[name]


def need_datetime(b, name):
    """Returns (parsed_utc_dt, raw_string)."""
    raw = need_str(b, name)
    try:
        dt = store.parse_iso_datetime(raw)
    except (ValueError, TypeError):
        bad_request("Field %s must be an ISO 8601 datetime" % name)
    return dt, raw


def try_datetime(b, name):
    """Parse if present and well-formed, else (None, raw-or-None)."""
    if not _present(b, name):
        return None, None
    raw = b[name]
    if not isinstance(raw, str):
        return None, raw
    try:
        return store.parse_iso_datetime(raw), raw
    except (ValueError, TypeError):
        return None, raw


def need_date_str(b, name):
    raw = need_str(b, name)
    try:
        store.parse_iso_date(raw)
    except (ValueError, TypeError):
        bad_request("Field %s must be an ISO 8601 date" % name)
    return raw
