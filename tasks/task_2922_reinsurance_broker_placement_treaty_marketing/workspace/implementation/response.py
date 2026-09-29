"""Response envelope helpers (PRD 2.2 / 2.3 / 2.6)."""
import json
import random
import string
from decimal import Decimal

from flask import Response

import db
from errors import ApiError
from util import fmt_instant

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj) + " is not JSON serialisable")


def _dump(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(db.now()),
    }


def object_response(data, status=200):
    return _dump({"meta": _meta(), "response_type": "object", "data": data}, status)


def list_response(rows, limit, offset, status=200):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return _dump({"meta": meta, "response_type": "array", "data": page}, status)


def error_response(err):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _dump(payload, err.http_status)


def error(error_id, message=None, status=None):
    return error_response(ApiError(error_id, message, status))
