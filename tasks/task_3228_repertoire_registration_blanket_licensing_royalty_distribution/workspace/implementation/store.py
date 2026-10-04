"""In-memory data store, logical clock, errors, and response envelope helpers.

Store starts EMPTY on every boot — no seeding anywhere.
"""
import random
import string
import threading
import uuid
from datetime import datetime, timezone

from flask import jsonify

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_INITIAL_CLOCK = "2026-09-01T00:00:00+00:00"


class LogicalClock:
    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime.fromisoformat(_INITIAL_CLOCK)

    def now(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt
            return self._now


CLOCK = LogicalClock()

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

DB = {
    "affiliates": {},
    "works": {},
    "share_claims": {},
    "licensees": {},
    "licenses": {},
    "disputes": {},
    "rate_court_cases": {},
    "performances": {},
    "cycles": {},
    "statements": {},
    "adjustments": {},
    "audits": {},
    "pools": {},
}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Timestamp in ISO 8601 UTC with three fractional digits (logical clock)."""
    dt = CLOCK.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def touch(resource):
    """Bump version + refresh updated_at on a resource dict."""
    resource["version"] = resource.get("version", 1) + 1
    resource["updated_at"] = now_iso()


def new_resource(fields):
    ts = now_iso()
    r = dict(fields)
    r["id"] = new_id()
    r["created_at"] = ts
    r["updated_at"] = ts
    r["version"] = 1
    return r


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_SHARE": 422,
    "ERR_WORK_SHARES_INCOMPLETE": 422,
    "ERR_CONFLICT_RESOLUTION_INVALID": 422,
    "ERR_WORK_NOT_CONFIRMED": 422,
    "ERR_WORK_HAS_PERFORMANCES": 422,
    "ERR_CLAIM_LOCKED_BY_DISTRIBUTION": 422,
    "ERR_LICENSEE_DELINQUENT": 422,
    "ERR_LICENSE_SUSPENDED": 422,
    "ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW": 422,
    "ERR_DISPUTE_ALREADY_OPEN": 409,
    "ERR_RATE_COURT_CASE_EXISTS": 409,
    "ERR_DISPUTE_NOT_WITHDRAWABLE": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CLAIMS_WINDOW_CLOSED": 422,
    "ERR_UNCLAIMED_POOL_INSUFFICIENT": 422,
    "ERR_ESCHEAT_NOT_YET_DUE": 422,
    "ERR_ESCHEAT_AMOUNT_INVALID": 422,
    "ERR_AUDIT_SCOPE_TOO_OLD": 422,
    "ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT": 422,
    "ERR_STATEMENTS_NOT_FINALIZED": 422,
    "ERR_CYCLE_NO_PERFORMANCES": 422,
}


def err(error_id, message):
    return ApiError(error_id, ERR[error_id], message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def success_object(data, http_status=200):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_list(items, total_count, limit, offset, http_status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(api_err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
