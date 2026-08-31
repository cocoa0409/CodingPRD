"""Response envelope, pagination and the per-request dirty-row tracker."""
import random
import string
from datetime import datetime, timezone

from flask import g, jsonify, request

from errors import ApiError
from store import JOURNAL_KINDS, serialize, store

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _request_ts()}
    if extra:
        meta.update(extra)
    return meta


# -- dirty-row tracking ---------------------------------------------------
def touch(row):
    """Mark a row as mutated by this request (PRD 2.4: a cascade counts)."""
    if row is None:
        return row
    dirty = getattr(g, "_dirty", None)
    if dirty is None:
        dirty = {}
        g._dirty = dirty
    dirty[id(row)] = row
    return row


def flush_dirty():
    dirty = getattr(g, "_dirty", None)
    if not dirty:
        return
    stamp = store.now_iso()
    for row in dirty.values():
        if row.get("_kind") in JOURNAL_KINDS:
            continue
        if "version" in row:
            row["updated_at"] = stamp
            row["version"] = row["version"] + 1
    g._dirty = {}


# -- responses ------------------------------------------------------------
def ok(data, status=200):
    flush_dirty()
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data) if isinstance(data, dict) and "_kind" in data else (data or {}),
    }
    return jsonify(payload), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    flush_dirty()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in window],
    }
    return jsonify(payload), 200


def error_response(err):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(payload), err.http_status


# -- pagination -----------------------------------------------------------
def read_pagination():
    """PRD 2.3 - limit defaults to 10 (1..100), offset defaults to 0 (>=0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _int_arg(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _int_arg(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def _int_arg(raw):
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination values must be integers.")
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Pagination values must be integers.")


def bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    return None
