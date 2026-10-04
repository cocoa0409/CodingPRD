"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import datetime

from flask import jsonify, request

import db
from errors import ApiError


def _meta():
    now = datetime.datetime.utcnow()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z"
    return {"api_request_id": db.new_request_id(), "api_request_timestamp": stamp}


def object_response(payload, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": payload}
    return jsonify(body), status


def array_response(rows, total_count, limit, offset, status=200):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(rows)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' may not exceed %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _int_param("offset", DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(rows, serializer):
    """Order by creation (ascending), then apply the offset/limit window."""
    limit, offset = pagination()
    ordered = sorted(rows, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return array_response([serializer(r) for r in window], total, limit, offset)


def serialize(row):
    """Drop internal bookkeeping fields."""
    return {k: v for k, v in row.items() if not k.startswith("_")}
