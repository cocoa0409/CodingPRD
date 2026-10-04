"""Response envelope helpers (PRD 2.2).

Success: {"meta": {api_request_id, api_request_timestamp[, pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    nw = datetime.now(timezone.utc)
    ts = nw.strftime("%Y-%m-%dT%H:%M:%S.") + f"{nw.microsecond // 1000:03d}Z"
    return {"api_request_id": rid, "api_request_timestamp": ts}


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total_count, limit, offset, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
