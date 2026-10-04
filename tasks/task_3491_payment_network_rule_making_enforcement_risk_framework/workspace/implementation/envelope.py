"""Response envelope helpers (PRD section 2.2 / scaffold response_envelope).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
List responses add limit/offset/total_count/has_more to meta.
api_request_timestamp renders in the 3-fractional-digit bookkeeping family.
"""
import secrets

from flask import jsonify

from clock import CLOCK, render_ts3
from errors import ERROR_CATALOG


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": render_ts3(CLOCK.now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_resp(error_id, message):
    status = ERROR_CATALOG.get(error_id, 500)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
