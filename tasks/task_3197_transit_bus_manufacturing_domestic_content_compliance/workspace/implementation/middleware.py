"""Auth middleware: X-User-ID / X-User-Role validation and RBAC."""
from flask import request
from errors import err_unauthenticated, err_forbidden

ROLES = {
    "PlatformAdmin",
    "ProcurementOfficer",
    "ConfigEngineer",
    "ComplianceOfficer",
    "SupplierRep",
    "Auditor",
    "ProductionPlanner",
    "AgencyInspector",
    "WarrantyAdmin",
    "AgencyAdmin",
}

# Per-endpoint RBAC matrix. Key: (METHOD, rule path) -> allowed roles.
# Defined in routes modules; here we keep a helper.


def current_user():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return uid, role


def require_roles(*allowed):
    uid, role = current_user()
    if role not in allowed:
        raise err_forbidden()
    return uid, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        from errors import err_invalid_request
        raise err_invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, *names):
    from errors import err_invalid_request
    for n in names:
        if n not in body or body[n] is None:
            raise err_invalid_request(f"Missing required field: {n}")


def opt_enum(body, name, allowed, required=False):
    from errors import err_invalid_request
    v = body.get(name)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {name}")
        return None
    if v not in allowed:
        raise err_invalid_request(f"Unknown enum member for {name}: {v}")
    return v


def opt_int(body, name, required=False):
    from errors import err_invalid_request
    v = body.get(name)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {name}")
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {name} must be an integer")
    return v
