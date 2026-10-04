"""Response envelope helpers per scaffold §1.0.

Success: {"meta": {"api_request_id": ..., "api_request_timestamp": ...},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
List responses add limit/offset/total_count/has_more into meta.
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import APIError

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _wall_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (now.microsecond // 1000) + "Z"


def success(data, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }
    response_type = "object"
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
        response_type = "array"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    if isinstance(err, APIError):
        error_id = err.error_id
        message = err.message
        status = err.http_status
    else:
        error_id = "ERR_INTERNAL"
        message = str(err)
        status = 500
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
