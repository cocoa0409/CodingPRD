"""Response envelope construction per PRD §2.2."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def envelope(data, response_type="object", status=200):
    body = {"meta": meta(), "response_type": response_type, "data": data}
    return jsonify(body), status


def envelope_list(items, limit, offset, total_count, has_more, status=200):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = has_more
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), status


def envelope_error(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
