"""Auth middleware and request validation helpers."""

from flask import request

from errors import raise_err

ALL_ROLES = {
    "PlatformAdmin",
    "NetworkPlanner",
    "CapacityEngineer",
    "FieldOpsCoordinator",
    "FranchiseAdmin",
    "ProvisioningAgent",
    "CustomerCare",
}


def require_roles(roles):
    """Auth checks (priority 1 and 2). `roles` is the declared role list;
    ['Any'] means any authenticated role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise_err("ERR_MISSING_AUTH_CONTEXT")
    if "Any" in roles:
        if role not in ALL_ROLES:
            raise_err("ERR_FORBIDDEN_ROLE")
        return role
    if role not in roles:
        raise_err("ERR_FORBIDDEN_ROLE")
    return role


def body_json(required=None, optional=None):
    """Parse the JSON body and validate required fields / enums.

    `required`/`optional`: list of (field_name, kind, allowed) tuples.
    kind: 'str', 'int', 'bool', 'array', 'datetime', 'number', 'any'
    allowed: set of allowed values for enums (or None).
    Returns dict of validated values (only declared fields are returned).
    """
    required = required or []
    optional = optional or []
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err("ERR_VALIDATION", "Request body must be a JSON object")
    out = {}
    for name, kind, allowed in required:
        if name not in data or data[name] is None:
            raise_err("ERR_VALIDATION", f"Missing required field: {name}")
        out[name] = _coerce(name, data[name], kind, allowed)
    for name, kind, allowed in optional:
        if name in data and data[name] is not None:
            out[name] = _coerce(name, data[name], kind, allowed)
        else:
            out[name] = None
    return out


def _coerce(name, value, kind, allowed):
    import db
    if kind == "str":
        if not isinstance(value, str):
            raise_err("ERR_VALIDATION", f"{name} must be a string")
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise_err("ERR_VALIDATION", f"{name} must be an integer")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise_err("ERR_VALIDATION", f"{name} must be a number")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise_err("ERR_VALIDATION", f"{name} must be a boolean")
    elif kind == "array":
        if not isinstance(value, list):
            raise_err("ERR_VALIDATION", f"{name} must be an array")
    elif kind == "datetime":
        try:
            db.parse_dt(value)
        except (ValueError, TypeError):
            raise_err("ERR_VALIDATION", f"{name} must be an ISO8601 datetime")
    elif kind == "any":
        pass
    if allowed is not None and value not in allowed:
        raise_err("ERR_VALIDATION", f"{name} has an illegal value")
    return value
