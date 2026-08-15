"""Request-body shape validation (priority 4) and path-resource resolution (priority 3)."""
from datetime import date, datetime, timezone

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def peek_body():
    from flask import request
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def require_path_resource(collection, rid, label="resource"):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{label} not found: {rid}")
    return rec


# ---------------------------------------------------------------------------
# Field validators — all raise ERR_INVALID_REQUEST (400) on shape violations
# ---------------------------------------------------------------------------

def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None or not _is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum)


def req_number(body, field, minimum=None):
    v = body.get(field)
    if v is None or not _is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    return v


def opt_number(body, field, default=None, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field, minimum=minimum)


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_date(body, field):
    v = req_str(body, field)
    try:
        d = date.fromisoformat(v)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an ISO date (YYYY-MM-DD)")
    if v != d.isoformat():
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an ISO date (YYYY-MM-DD)")
    return v


def req_datetime(body, field):
    from util import parse_datetime
    v = req_str(body, field)
    try:
        parse_datetime(v)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an ISO 8601 datetime")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def get_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
