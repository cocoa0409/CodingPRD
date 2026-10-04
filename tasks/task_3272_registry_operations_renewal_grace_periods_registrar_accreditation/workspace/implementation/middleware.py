from flask import request

from errors import err_unauthenticated, err_forbidden, err_invalid_request

ROLES = {"RegistryAdmin", "RegistrarOperator", "RegistryFinance", "AbuseAnalyst"}


def get_auth():
    """Extract and validate X-User-Role / X-User-ID. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not user_id:
        raise err_unauthenticated()
    return role, user_id


def require_roles(*allowed):
    role, user_id = get_auth()
    if role not in allowed:
        raise err_forbidden()
    return role, user_id


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset
