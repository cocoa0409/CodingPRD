"""Response envelope, error handling, auth, pagination, and timestamp helpers."""
import uuid
import random
import string
from datetime import datetime, timezone

from flask import request

from store import STATE, LOCK


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ROLES = {
    "PlatformOperator",
    "TenantAdministrator",
    "ImplementationPartner",
    "Approver",
    "IntegrationDeveloper",
}


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def iso_now():
    """Logical clock timestamp, ISO 8601 UTC with three fractional digits."""
    dt = STATE["clock"]
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 timestamp (accepts trailing Z). Returns aware datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Expected ISO-8601 timestamp string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Malformed timestamp: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return body, status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return body, 200


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return body, err.http_status


def new_id():
    return str(uuid.uuid4())


def get_auth():
    """Priority 1/2: authentication. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role / X-User-ID headers")
    return user_id, role


def require_roles(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
    return user_id, role


def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "JSON body must be an object")
    return body


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ascending (insertion order proxy via created_seq), then paginate."""
    limit, offset = pagination_params()
    items = sorted(items, key=lambda x: (x.get("_seq", 0),))
    total = len(items)
    page = items[offset:offset + limit]
    for it in page:
        it.pop("_seq", None)
    return success_list(page, limit, offset, total)


def strip_internal(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}
