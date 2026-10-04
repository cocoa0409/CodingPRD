"""Response envelope, pagination, and request validation helpers."""
import uuid
from datetime import datetime, timezone
from flask import jsonify, request
from db import ts_now
from errors import err

VALID_ROLES = {
    "PlantManager", "MillOperator", "Scheduler", "Metallurgist",
    "ProcurementOfficer", "AccountManager", "QualityEngineer",
    "EnergyDispatcher",
}


def ok(data, status=200):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": ts_now(),
        },
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, total, limit, offset, status=200):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": ts_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(items)) < total,
        },
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or invalid X-User-ID / X-User-Role")
    return uid, role


def require_role(*roles):
    uid, role = require_auth()
    if role not in roles:
        raise err("ERR_FORBIDDEN", "role not permitted for this endpoint")
    return uid, role


def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
    return body


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"missing or invalid field: {name}")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"field {name} must be one of {sorted(allowed)}")
    return v


def req_num(body, name, gt=None, ge=None, le=None, lt=None):
    v = body.get(name)
    if not _is_num(v):
        raise err("ERR_INVALID_REQUEST", f"missing or invalid numeric field: {name}")
    if gt is not None and not (v > gt):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be >= {ge}")
    if le is not None and not (v <= le):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be <= {le}")
    if lt is not None and not (v < lt):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be < {lt}")
    return v


def req_int(body, name, gt=None, ge=None, le=None):
    v = body.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"missing or invalid integer field: {name}")
    if gt is not None and not (v > gt):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be >= {ge}")
    if le is not None and not (v <= le):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be <= {le}")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"missing or invalid boolean field: {name}")
    return v


def opt_num(body, name, default=None, ge=None, le=None):
    v = body.get(name, default)
    if v is None:
        return default
    if not _is_num(v):
        raise err("ERR_INVALID_REQUEST", f"invalid numeric field: {name}")
    if ge is not None and not (v >= ge):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be >= {ge}")
    if le is not None and not (v <= le):
        raise err("ERR_INVALID_REQUEST", f"field {name} must be <= {le}")
    return v


def parse_dt(s, name):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", f"invalid datetime field: {name}")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"invalid datetime field: {name}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(s, name):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", f"invalid date field: {name}")
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"invalid date field: {name}")
    return s


def parse_month(s, name):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", f"invalid month field: {name}")
    try:
        datetime.strptime(s, "%Y-%m")
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"invalid month field: {name}")
    if len(s) != 7:
        raise err("ERR_INVALID_REQUEST", f"invalid month field: {name}")
    return s


def pagination():
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid limit")
    try:
        offset = int(args.get("offset", "0"))
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid offset")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit out of range")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset out of range")
    return limit, offset


def apply_filters(rows, mapping):
    """mapping: {query_param: entity_field}; skip params that are None."""
    out = []
    for row in rows:
        keep = True
        for param, field in mapping.items():
            v = request.args.get(param)
            if v is not None and str(row.get(field)) != v:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def list_response(all_rows, filters=None):
    rows = sorted(all_rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    if filters:
        rows = apply_filters(rows, filters)
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(page, total, limit, offset)
