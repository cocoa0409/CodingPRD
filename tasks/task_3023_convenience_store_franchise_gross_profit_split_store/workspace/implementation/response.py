"""Response envelope helpers (scaffold §1.0 `response_envelope`)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def new_request_id():
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + tail


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": _utc_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, pagination=None):
    """Successful envelope: meta / response_type / data."""
    if pagination is not None:
        body = {"meta": _meta(pagination), "response_type": "array", "data": data}
    elif isinstance(data, list):
        body = {"meta": _meta(), "response_type": "array", "data": data}
    else:
        body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status