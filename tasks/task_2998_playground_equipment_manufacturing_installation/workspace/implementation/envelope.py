"""Response envelope helpers (PRD section 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"


def _now_iso():
    return iso_millis(datetime.now(timezone.utc))


def _base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()}


def object_response(data, status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def no_content_response():
    """HTTP 204 for placement removal (PRD section 4)."""
    return "", 204
