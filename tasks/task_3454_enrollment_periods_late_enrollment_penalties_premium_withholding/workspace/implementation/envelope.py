"""Response envelope helpers — exact structure from the scaffold:

success: { "meta": { "api_request_id", "api_request_timestamp"[, pagination] },
           "response_type": "object" | "array", "data": ... }
error:   { "meta": { "api_request_id", "api_request_timestamp" },
           "response_type": "error", "data": { "error_id", "message" } }
"""
from __future__ import annotations

import secrets

from flask import jsonify

from clock import format_ts, now


def _meta() -> dict:
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": format_ts(now()),
    }


def success_object(data, status: int = 200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_payload(error_id: str, message: str) -> dict:
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
