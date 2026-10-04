"""Response envelope helpers and auth/RBAC middleware."""
import secrets
import string
from flask import jsonify, request

import clock
from errors import ApiError, raise_err

ROLES = {
    "Anonymous", "Contributor", "BusinessOwner", "Moderator",
    "PolicyAnalyst", "ImageryOperator", "RoutingEngineer", "PlatformAdmin",
}


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def envelope(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(err):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    def _int(name, default):
        raw = args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "invalid %s" % name)

    limit = _int("limit", 10)
    offset = _int("offset", 0)
    if limit < 1 or limit > 100:
        raise_err("ERR_INVALID_REQUEST", "limit out of range")
    if offset < 0:
        raise_err("ERR_INVALID_REQUEST", "offset out of range")
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending, then slice; returns (page, pagination)."""
    items = sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    limit, offset = parse_pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


def current_actor():
    """Validate auth headers; returns (role, user_id). Raises ApiError."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "missing or invalid X-User-Role")
    if role != "Anonymous" and not uid:
        raise_err("ERR_UNAUTHENTICATED", "missing X-User-ID")
    return role, uid


def require_roles(allowed):
    role, uid = current_actor()
    if role not in allowed:
        raise_err("ERR_UNAUTHORIZED", "role %s not permitted" % role)
    return role, uid


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data
