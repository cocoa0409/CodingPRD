"""Request identity, role checking and the response envelope."""

import random
import string

from flask import jsonify

import constants as C
import store
from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ApiError


ALPHABET = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALPHABET) for _ in range(18))


def meta_block(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _clean(value):
    """Drop server-internal keys (leading underscore) from a payload."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def ok(data, response_type="object", meta_extra=None, status=200):
    return jsonify({
        "meta": meta_block(meta_extra),
        "response_type": response_type,
        "data": _clean(data),
    }), status


def ok_list(rows, page_meta):
    return ok(rows, response_type="array", meta_extra=page_meta, status=200)


def error_response(error):
    return jsonify({
        "meta": meta_block(),
        "response_type": "error",
        "data": {
            "error_id": error.error_id,
            "message": error.message,
        },
    }), error.http_status


# --- identity ----------------------------------------------------------------
def authenticate(headers, endpoint_key):
    """Validate the two identity headers and the role's admission to the route.

    Authentication runs first, authorization second (PRD 2.4); both are tested
    before any resource is resolved.
    """
    role = headers.get("X-User-Role")
    user_id = headers.get("X-User-ID")
    if not role or not user_id:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role and X-User-ID are required", 401)
    if role not in C.ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "unknown role", 401)
    if role == "Customer" and user_id not in store.customers:
        raise ApiError(ERR_UNAUTHENTICATED, "unknown customer identity", 401)
    admitted = C.ENDPOINT_ROLES.get(endpoint_key)
    if admitted is None:
        raise ApiError(ERR_UNAUTHORIZED, "no role admits this operation", 403)
    if role not in admitted:
        raise ApiError(ERR_UNAUTHORIZED, "role is not admitted to this operation", 403)
    return role, user_id


def require_customer_scope(role, user_id, customer_id):
    """A Customer may only reach its own resources."""
    if role == "Customer" and user_id != customer_id:
        raise ApiError(ERR_UNAUTHORIZED, "customer may only read its own contracts", 403)
