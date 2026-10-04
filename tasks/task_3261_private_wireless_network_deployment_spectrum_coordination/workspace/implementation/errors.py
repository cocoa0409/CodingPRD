"""Error definitions and envelope helpers."""

import random
import string
from flask import jsonify

from db import DB


HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTY": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_INVALID_TIME_WINDOW": 400,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_CAPACITY_SHORTFALL": 422,
    "ERR_TARGET_CAPACITY_TOO_LOW": 422,
    "ERR_SURVEY_SIGNAL_TOO_WEAK": 422,
    "ERR_INTERFERENCE_MARGIN_EXCEEDED": 422,
    "ERR_SPECTRUM_OVERLAP": 409,
    "ERR_NO_ACTIVE_LEASE": 422,
    "ERR_ASSIGNMENT_OVERLAP": 409,
    "ERR_LEASE_BANDWIDTH_EXCEEDED": 422,
    "ERR_CONTRACT_OVERLAP": 409,
    "ERR_SLICE_BANDWIDTH_EXCEEDED": 422,
    "ERR_SLICE_DEVICE_CAP_EXCEEDED": 422,
    "ERR_URLLC_REQUIRES_EDGE": 422,
    "ERR_REMEDIATION_CELLS_MISSING": 422,
    "ERR_REMEDIATION_OPEN": 422,
    "ERR_CROSS_ENTERPRISE_REFERENCE": 422,
    "ERR_CHILDREN_ACTIVE": 422,
    "ERR_ENTERPRISE_CHILDREN_ACTIVE": 422,
    "ERR_STALE_SITE_VERSION": 412,
    "ERR_STALE_REQUEST_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = HTTP_STATUS[error_id]


def err(error_id, message):
    return ApiError(error_id, message)


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def now_iso():
    """Logical-clock timestamp, ISO 8601 UTC with 3 fractional digits."""
    dt = DB.clock
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def wall_iso():
    """Wall-clock timestamp for meta.api_request_timestamp."""
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def ok_object(data, code=200):
    body = {
        "meta": {"api_request_id": new_request_id(), "api_request_timestamp": wall_iso()},
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def ok_list(items, total, limit, offset, code=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), code


def error_response(e):
    body = {
        "meta": {"api_request_id": new_request_id(), "api_request_timestamp": wall_iso()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status
