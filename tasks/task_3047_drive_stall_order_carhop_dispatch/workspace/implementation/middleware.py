"""Auth header extraction, role checking, request validation helpers (PRD 2.1, 2.10)."""
from flask import request

from errors import raise_error, invalid_request

ROLES = ["PlatformAdmin", "ShiftManager", "KitchenStaff", "Carhop", "Customer"]
ENTITY_BACKED_ROLES = {"Carhop", "Customer"}


def require_auth(allowed_roles):
    """Validate X-User-Role / X-User-ID headers and endpoint role permission.

    Returns (user_id, role).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise_error("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role header")
    if user_id is None or user_id == "":
        raise_error("ERR_UNAUTHENTICATED", "Missing X-User-ID header")
    if role not in allowed_roles:
        raise_error("ERR_FORBIDDEN", "Role {} not permitted on this endpoint".format(role))
    return user_id, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        invalid_request("Request body must be a JSON object")
    return data


def get_str(body, field, required=False, default=None):
    v = body.get(field, default)
    if v is None:
        if required:
            invalid_request("Missing required field: {}".format(field))
        return None
    if not isinstance(v, str):
        invalid_request("Field {} must be a string".format(field))
    return v


def get_enum(body, field, values, required=False, default=None):
    v = body.get(field, default)
    if v is None:
        if required:
            invalid_request("Missing required field: {}".format(field))
        return None
    if not isinstance(v, str) or v not in values:
        invalid_request("Field {} must be one of {}".format(field, values))
    return v


def get_bool(body, field, required=False, default=None):
    v = body.get(field, default)
    if v is None:
        if required:
            invalid_request("Missing required field: {}".format(field))
        return None
    if not isinstance(v, bool):
        invalid_request("Field {} must be a boolean".format(field))
    return v


def get_int(body, field, required=False, default=None, minimum=None):
    v = body.get(field, default)
    if v is None:
        if required:
            invalid_request("Missing required field: {}".format(field))
        return None
    if not isinstance(v, int) or isinstance(v, bool):
        invalid_request("Field {} must be an integer".format(field))
    if minimum is not None and v < minimum:
        invalid_request("Field {} must be >= {}".format(field, minimum))
    return v


def get_num(body, field, required=False, default=None):
    v = body.get(field, default)
    if v is None:
        if required:
            invalid_request("Missing required field: {}".format(field))
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid_request("Field {} must be a number".format(field))
    return v


def get_str_list(body, field, required=False, default=None):
    v = body.get(field, default)
    if v is None:
        if required:
            invalid_request("Missing required field: {}".format(field))
        return None
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        invalid_request("Field {} must be a list of strings".format(field))
    return v


def pagination_params():
    """Read limit/offset query params (defaults 10/0; limit in [1,100]; offset >= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            invalid_request("limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        invalid_request("limit must be between 1 and 100")
    if offset < 0:
        invalid_request("offset must be >= 0")
    return limit, offset


def sort_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


def query_filters(allowed):
    """Build a dict of simple equality filters from query args."""
    filters = {}
    for name in allowed:
        v = request.args.get(name)
        if v is not None:
            filters[name] = v
    return filters
