import random
import string
import uuid

from flask import jsonify, request

from clock import iso_now
from errors import ApiError
from models import ROLES


def request_id():
    return "req_" + uuid.uuid4().hex[:20]


def success_object(obj, status=200):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "object",
        "data": obj,
    }
    return jsonify(body), status


def success_list(items):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": iso_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + limit < total,
        },
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def pagination_params():
    limit_raw = request.args.get("limit", None)
    offset_raw = request.args.get("offset", None)
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def current_actor():
    """Return (user_id, role) after validating presence + recognized role.

    Raises ERR_UNAUTHENTICATED if missing/unrecognized.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognized authentication headers", 401)
    return user_id, role


def require_role(*allowed):
    user_id, role = current_actor()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted for this endpoint", 403)
    return user_id, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return body


def sort_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
