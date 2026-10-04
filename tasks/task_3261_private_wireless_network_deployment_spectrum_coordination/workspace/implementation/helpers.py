"""Shared helpers: ids, timestamps, parsing, pagination, serialization."""

import math
import uuid
from datetime import datetime, timezone

from flask import request

from db import DB
from errors import err, now_iso


# ---------------------------------------------------------------- ids / stamps

def new_id():
    return str(uuid.uuid4())


def stamp():
    return now_iso()


def touch(res):
    """Bump updated_at and version on a common-fields resource."""
    res["updated_at"] = now_iso()
    res["version"] = res.get("version", 1) + 1


def new_resource(common=True):
    ts = now_iso()
    res = {"id": new_id(), "created_at": ts}
    if common:
        res["updated_at"] = ts
        res["version"] = 1
    return res


# ---------------------------------------------------------------- time parsing

def parse_iso(value, field):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_of(dt):
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def check_window(start_s, end_s):
    """Half-open window: end must be strictly later than start."""
    s = parse_iso(start_s, "start")
    e = parse_iso(end_s, "end")
    if e <= s:
        raise err("ERR_INVALID_TIME_WINDOW", "Time window end must be strictly later than start")
    return s, e


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap: share at least one instant."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------- body fields

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string")
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_int(body, name, minimum=None, maximum=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be <= {maximum}")
    return v


def opt_int(body, name, default, minimum=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {minimum}")
    return v


def req_num(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


# ---------------------------------------------------------------- pagination

def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def apply_filters(items, filters):
    """filters: list of (query_param, record_field)."""
    for qp, field in filters:
        val = request.args.get(qp)
        if val is not None:
            items = [r for r in items if str(r.get(field)) == val]
    return items


def paged(items):
    """Sort by created_at ascending, paginate; returns (window, total, limit, offset)."""
    limit, offset = page_params()
    items = sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(items)
    return items[offset:offset + limit], total, limit, offset


# ---------------------------------------------------------------- serialization

def serialize(res):
    out = {}
    for k, v in res.items():
        out[k] = v
    return out
