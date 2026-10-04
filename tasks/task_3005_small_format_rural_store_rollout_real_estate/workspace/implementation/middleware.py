"""Auth header extraction, role checking, body helpers."""
from flask import request

from errors import err_unauthenticated, err_forbidden, err_invalid_request

ROLES = {
    "PROGRAM_ADMIN",
    "REAL_ESTATE_MANAGER",
    "NETWORK_PLANNER",
    "OPERATIONS_LEAD",
    "FINANCE_ANALYST",
}


def get_role():
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err_unauthenticated()
    return role


def get_user_id():
    return request.headers.get("X-User-ID")


def require_roles(*roles):
    role = get_role()
    if role not in roles:
        raise err_forbidden()
    return role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"missing required field: {f}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise err_invalid_request(f"{field} must be a non-empty string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    return v


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    return v


def opt_number(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    return v
