"""Error classes, response envelope helpers, auth/RBAC middleware."""
import random
import string
from datetime import datetime, timezone
from flask import request, jsonify, g

from store import DB


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for endpoint or ownership check failed"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_validation(msg="Malformed request"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_stale_version(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=22))


def wall_timestamp():
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def meta(pagination=None):
    m = {"api_request_id": new_request_id(), "api_request_timestamp": wall_timestamp()}
    if pagination:
        m.update(pagination)
    return m


def ok_object(data, status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), status


def ok_array(items, total_count, limit, offset, status=200):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return jsonify({"meta": meta(page), "response_type": "array", "data": items}), status


def error_response(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


ROLES = {"PlatformAdmin", "InstitutionalAdmin", "Instructor", "Student"}


def require_auth():
    """Priority-1 auth check. Sets g.user_id / g.user_role. Raises ApiError 401."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    g.user_id = uid
    g.user_role = role


def require_role(*roles):
    """Priority-2 role check. Raises ApiError 403."""
    if g.user_role not in roles:
        raise err_forbidden()


def get_pagination():
    """Parse limit/offset query params with defaults limit=10, offset=0.
    Bounds: 1 <= limit <= 100. Out-of-range or malformed -> ERR_VALIDATION."""
    args = request.args
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    try:
        limit = 10 if limit_s is None else int(limit_s)
    except (TypeError, ValueError):
        raise err_validation("limit must be an integer")
    try:
        offset = 0 if offset_s is None else int(offset_s)
    except (TypeError, ValueError):
        raise err_validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_validation("limit must be within 1..100")
    if offset < 0:
        raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items_sorted):
    limit, offset = get_pagination()
    total = len(items_sorted)
    window = items_sorted[offset:offset + limit]
    return ok_array(window, total, limit, offset)


def sort_by_created(items):
    """Sort by created_at ascending; created_at is an ISO string — lexical sort works
    because format is fixed-width, but also tie-break by insertion via stable sort."""
    return sorted(items, key=lambda e: e["created_at"])


def get_body():
    if not request.is_json:
        raise err_validation("Request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data
