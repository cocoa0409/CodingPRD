"""Validation plumbing + response envelope + pagination (PRD §2.2, §2.3, §2.8).

Stage helpers used by every endpoint so the §2.8 priority order is a single
ordered pipeline rather than ad-hoc per-endpoint if-chains:
  1-2  rbac.auth(...)
  3    body() + f_* shape extractors (ERR_INVALID_REQUEST)
  4    get_or_404(...) left-to-right (ERR_NOT_FOUND)
  5+   ownership / state / OCC / business checks in the endpoint modules

Entities are plain dicts. Datetimes are stored as aware datetimes and rendered
by ser(); keys starting with "_" are internal (insertion seq for stable sort).
"""
import uuid
from datetime import datetime

from flask import request, jsonify

import clock
import store
from errors import ApiError


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------

def _req_id():
    return "req_" + uuid.uuid4().hex[:24]


def envelope_ok(data, code=200, pagination=None):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    rtype = "array" if isinstance(data, list) else "object"
    resp = jsonify({"meta": meta, "response_type": rtype, "data": data})
    return resp, code


def envelope_error(err):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    resp = jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    })
    return resp, err.status


# ---------------------------------------------------------------------------
# Stage 3 — request shape
# ---------------------------------------------------------------------------

def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        _bad("Request body must be a JSON object")
    return b


def f_str(b, name, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            _bad("Missing required field: %s" % name)
        return default
    if not isinstance(v, str):
        _bad("Field %s must be a string" % name)
    return v


def f_int(b, name, required=True, default=None, min_v=None, max_v=None):
    v = b.get(name)
    if v is None:
        if required:
            _bad("Missing required field: %s" % name)
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field %s must be an integer" % name)
    if min_v is not None and v < min_v:
        _bad("Field %s must be >= %s" % (name, min_v))
    if max_v is not None and v > max_v:
        _bad("Field %s must be <= %s" % (name, max_v))
    return v


def f_num(b, name, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            _bad("Missing required field: %s" % name)
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field %s must be a number" % name)
    return v


def f_bool(b, name, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            _bad("Missing required field: %s" % name)
        return default
    if not isinstance(v, bool):
        _bad("Field %s must be a boolean" % name)
    return v


def f_enum(b, name, allowed, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            _bad("Missing required field: %s" % name)
        return default
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def f_dt(b, name, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            _bad("Missing required field: %s" % name)
        return default
    try:
        return clock.parse_dt(v)
    except (ValueError, TypeError):
        _bad("Field %s must be an ISO 8601 datetime" % name)


# ---------------------------------------------------------------------------
# Stage 4 — existence (left-to-right)
# ---------------------------------------------------------------------------

def get_or_404(mapping, key, label="Resource"):
    ent = mapping.get(key)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found: %s" % (label, key))
    return ent


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Lists sort by created_at ascending (insertion order breaks ties).
# ---------------------------------------------------------------------------

def page_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
    if limit < 1 or limit > 100:
        _bad("limit must be between 1 and 100")
    if offset < 0:
        _bad("offset must be >= 0")
    return limit, offset


def slice_page(items, limit, offset):
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [ser(e) for e in page], meta


# ---------------------------------------------------------------------------
# Entity plumbing (PRD §2.5)
# ---------------------------------------------------------------------------

def new_entity():
    """Common fields for the 13 primary resources."""
    now = clock.now_dt()
    return {
        "id": store.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def new_append():
    """Append-only records carry only id + created_at (§2.5)."""
    return {
        "id": store.new_id(),
        "created_at": clock.now_dt(),
        "_seq": store.next_seq(),
    }


def touch(ent):
    """Every mutation refreshes updated_at and increments version by one (§2.5/§2.9)."""
    ent["updated_at"] = clock.now_dt()
    ent["version"] += 1


def ser(ent):
    out = {}
    for k, v in ent.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = clock.iso(v)
        else:
            out[k] = v
    return out
