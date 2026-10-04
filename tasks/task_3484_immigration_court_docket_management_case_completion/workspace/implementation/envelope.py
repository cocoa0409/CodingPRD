# envelope.py — response envelope builders per SCAFFOLD §1.0 / PRD §2.2.
import uuid
from flask import jsonify

import db
from timeutil import fmt


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt(db.get_clock()),
    }


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, http_status):
    return jsonify(error_body(error_id, message)), http_status


def list_response(serialized_items, total_count, limit, offset):
    """List envelope: pagination fields live in `meta` (PRD §2.3)."""
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(serialized_items) < total_count,
    }
    return success(serialized_items, response_type="array", status=200,
                   pagination=pagination)
