"""Response envelope + auth middleware helpers."""
import uuid
from datetime import datetime, timezone
from flask import request, jsonify

import errors


def now_iso():
    """Wall-clock timestamp for meta (3 fractional digits, Z suffix)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ok(data, status=200, pagination=None):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": now_iso(),
        },
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def fail(api_err):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    resp = jsonify(body)
    resp.status_code = api_err.http_status
    return resp


DECLARED_ROLES = {
    "OpsAdmin", "MillPlanner", "BranchManager", "CreditManager",
    "AccountManager", "FleetCoordinator", "BuilderContact",
}


def auth_context():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise errors.err_missing_context()
    return user_id, role


def require_role(*allowed):
    user_id, role = auth_context()
    if role not in allowed:
        raise errors.err_forbidden()
    return user_id, role
