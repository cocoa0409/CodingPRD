"""Auth middleware per PRD §2.1 and validations priority 1-2."""
from flask import request
from errors import raise_err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_UNAUTHORIZED_ROLE

ROLES = {
    "ProgramDirector",
    "Registrar",
    "PlacementOfficer",
    "CastingDirector",
    "FinanceOfficer",
    "Student",
}


def auth(allowed_roles):
    """Validate headers then role authorization. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str):
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, "missing X-User-ID header")
    if not role or role not in ROLES:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, "missing or invalid X-User-Role header")
    if role not in allowed_roles:
        raise_err(ERR_UNAUTHORIZED_ROLE, "role not authorized for this endpoint")
    return user_id, role


def require_student_owner(user_id, role, owner_student_id):
    """Student role may only act on own resources; staff roles bypass."""
    if role == "Student" and user_id != owner_student_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "student may only act on own resources")


def pagination_params():
    """Parse limit/offset per §2.3. Defaults limit=10, offset=0; 1<=limit<=100."""
    from errors import invalid_request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        invalid_request("limit must be between 1 and 100")
    if offset < 0:
        invalid_request("offset must be >= 0")
    return limit, offset


def json_body():
    """Return request JSON body or {} — reject malformed JSON."""
    from errors import invalid_request
    if not request.data:
        return {}
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        invalid_request("request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid_request("request body must be a JSON object")
    return data


def require_fields(body, fields):
    from errors import invalid_request
    for f in fields:
        if f not in body or body[f] is None:
            invalid_request(f"missing required field: {f}")
