"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import serialize

ALNUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def api_request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": api_request_timestamp(),
    }


def ok(data=None, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_row(row, status=200):
    return ok(serialize(row), status)


def ok_list(rows, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status
