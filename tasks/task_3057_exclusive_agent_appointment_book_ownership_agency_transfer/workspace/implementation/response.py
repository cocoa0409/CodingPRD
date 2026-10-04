"""Response envelope helpers (PRD §2.2, SCAFFOLD response_envelope).

Success:
    { "meta": {api_request_id, api_request_timestamp[, limit, offset,
               total_count, has_more]},
      "response_type": "object" | "array",
      "data": <object|array> }

Error:
    { "meta": {api_request_id, api_request_timestamp},
      "response_type": "error",
      "data": {error_id, message} }
"""

from flask import jsonify

import clock


def _meta(extra=None):
    meta = {
        "api_request_id": clock.new_request_id(),
        "api_request_timestamp": clock.iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def empty_response(pagination=None):
    """2xx with no payload — data is an empty object."""
    return object_response({}, 200, pagination)


def error_response(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": clock.new_request_id(),
            "api_request_timestamp": clock.iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status