"""Response envelope, pagination and error construction (§2.2, §2.3)."""
import json
import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify
from flask.json.provider import DefaultJSONProvider

from catalog import ERROR_STATUS
from store import fmt_dt, DB

ALPHA = string.ascii_uppercase + string.digits


class SafeJSON(DefaultJSONProvider):
    """JSON provider that serialises datetimes as ISO 8601 UTC with millisecond
    precision, and never re-formats strings (the default provider rewrites
    ISO-shaped strings as HTTP dates)."""

    @staticmethod
    def default(obj):
        if isinstance(obj, datetime):
            return fmt_dt(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return int(obj)
        raise TypeError("Object of type %s is not JSON serializable"
                        % type(obj).__name__)


def request_id():
    return "req_" + "".join(random.choice(ALPHA) for _ in range(18))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(DB.now()),
    }


def ok(data, status=200, response_type=None):
    body = {"meta": _meta()}
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    body["response_type"] = response_type
    body["data"] = data if data is not None else {}
    return jsonify(body), status


def paginated(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {"meta": meta, "response_type": "array", "data": window}
    return jsonify(body), 200


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.status = status or ERROR_STATUS.get(error_id, 400)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# short constructors used throughout the services
def unauth(msg="Missing or blank credentials."):
    return ApiError("ERR_UNAUTHENTICATED", msg)


def forbidden(msg="The acting role may not perform this operation."):
    return ApiError("ERR_UNAUTHORIZED", msg)


def not_found(msg="The referenced resource does not exist."):
    return ApiError("ERR_NOT_FOUND", msg)


def invalid_state(msg="The resource is not in a state from which this operation is allowed."):
    return ApiError("ERR_INVALID_STATE", msg)


def stale(msg="The expected version does not match the stored version."):
    return ApiError("ERR_STALE_VERSION", msg)


def invalid_request(msg="A required field is missing or out of range."):
    return ApiError("ERR_INVALID_REQUEST", msg)


def value_rejected(msg="The field carries a value outside its declared set."):
    return ApiError("ERR_VALUE_REJECTED", msg)