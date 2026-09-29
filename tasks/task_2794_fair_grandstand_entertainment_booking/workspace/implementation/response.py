"""Response envelope helpers (PRD section 2.2)."""

import random
import string

from flask import jsonify

from db import now_str, public, sort_key

ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_str()}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows, limit, offset):
    """Apply the page window and report the pre-window total."""
    total = len(rows)
    return rows[offset:offset + limit], total


def collection(rows, limit, offset, field="created_at", reverse=False):
    """Order, page and serialise a filtered collection."""
    ordered = sorted(rows, key=lambda r: sort_key(r, field), reverse=reverse)
    page, total = paginate(ordered, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)
