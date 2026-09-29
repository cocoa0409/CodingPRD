"""Response envelope helpers -- PRD 2.2 and 2.3."""

from flask import jsonify

from core import logical_now_iso, new_request_id


def _meta():
    # PRD 2.5 is absolute: "Nothing in this system reads the host machine's wall
    # clock", so even the envelope timestamp is served from the logical clock. It
    # is still an ISO 8601 UTC instant with three fractional digits (PRD 2.2).
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": logical_now_iso(),
    }


def ok(data, status=200):
    """Single-resource (or empty) success envelope. Omits the pagination fields."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
