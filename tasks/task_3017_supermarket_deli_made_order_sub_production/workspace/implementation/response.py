"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2).

    { "meta": {"api_request_id": ..., "api_request_timestamp": ...},
      "response_type": "object" | "array" | "error",
      "data": ... }

List responses add ``limit``, ``offset``, ``total_count`` and ``has_more`` to
``meta``; error responses carry only the two identity fields there.
"""
import time

from flask import jsonify

from util import fmt_dt

PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def _req_id():
    raw = "%d%06d" % (int(time.time() * 1000) % 10 ** 6, int(time.time() * 10 ** 6) % 10 ** 6)
    return "req_" + raw[:18].upper().ljust(18, "0")


def _meta(runner):
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_dt(runner.now()),
    }


def ok_object(runner, obj, status=200):
    return jsonify({"meta": _meta(runner), "response_type": "object", "data": obj}), status


def ok_array(runner, items, limit, offset, total_count, status=200):
    meta = _meta(runner)
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error_body(runner, error_id, message):
    return {
        "meta": _meta(runner),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items, limit, offset):
    """Apply the offset/limit window and report the unwindowed total."""
    total = len(items)
    window = items[offset:offset + limit]
    return window, total