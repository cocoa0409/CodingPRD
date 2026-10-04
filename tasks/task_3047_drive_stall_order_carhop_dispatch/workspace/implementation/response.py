"""Response envelope helpers (PRD 2.2)."""
import random
import string
from flask import jsonify

from db import now


def _fmt_ts(dt):
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return s + ".{:03d}Z".format(dt.microsecond // 1000)


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _fmt_ts(now()),
    }


def success_object(data, status_code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status_code


def success_array(items, limit, offset, total_count, status_code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status_code


def success_no_data(status_code=204):
    if status_code == 204:
        return "", 204
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status_code


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
