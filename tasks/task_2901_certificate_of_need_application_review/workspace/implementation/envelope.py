"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

ALPHANUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _stamp():
    moment = datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": _stamp()}


def public(record):
    """Strip internal bookkeeping keys from a stored record."""
    if record is None:
        return None
    return {key: value for key, value in record.items() if not key.startswith("_")}


def ok(data=None, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": public(data) if isinstance(data, dict) else ({} if data is None else data),
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(row) for row in rows],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
