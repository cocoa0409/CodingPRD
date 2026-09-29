"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify

import store

_ALPHANUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def iso3(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % millis


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": iso3(store.db.clock),
    }


def scrub(value):
    """Recursively convert internal python values into JSON-friendly ones."""
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if key.startswith("_"):
                continue
            out[key] = scrub(val)
        return out
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": scrub(data if data is not None else {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [scrub(r) for r in rows],
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
