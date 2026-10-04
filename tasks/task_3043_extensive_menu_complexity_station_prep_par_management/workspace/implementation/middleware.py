from flask import request

from errors import ApiError, err_forbidden, err_missing_user_context

ALL_ROLES = [
    "SystemAdmin",
    "MenuAdmin",
    "KitchenManager",
    "PrepCook",
    "LineCook",
    "PastryChef",
    "InventoryController",
]


def get_user_context():
    """Rung 1: header presence. Returns (user_id, role). Raises on failure."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid == "" or role is None or role == "":
        raise err_missing_user_context()
    return uid, role


def require_roles(*roles):
    """Rung 3: role authorization. Call after body validation."""
    uid, role = get_user_context()
    if role not in roles:
        raise err_forbidden()
    return uid, role


def get_json_body():
    """Return parsed JSON object body, or raise ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data
