"""Response envelope helpers -- PRD section 2.2 / scaffold response_envelope.

    success: { "meta": {api_request_id, api_request_timestamp[, limit, offset,
                        total_count, has_more]},
               "response_type": "object" | "array", "data": ... }
    error:   { "meta": {api_request_id, api_request_timestamp},
               "response_type": "error",
               "data": {"error_id": ..., "message": ...} }
"""

import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def request_timestamp():
    now = datetime.now(timezone.utc)
    return "%s.%03dZ" % (now.strftime("%Y-%m-%dT%H:%M:%S"), now.microsecond // 1000)


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": request_timestamp(),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        # every date object in the store is an agronomic calendar field (PRD 2.5)
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def respond(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": jsonable(list(items)),
    }
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
