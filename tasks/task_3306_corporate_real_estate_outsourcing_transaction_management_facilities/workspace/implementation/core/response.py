"""Response envelope helpers (PRD 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def request_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": request_timestamp()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, pagination=None):
    if data is None:
        data = {}
    rtype = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": _meta(pagination), "response_type": rtype, "data": data}), status


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status