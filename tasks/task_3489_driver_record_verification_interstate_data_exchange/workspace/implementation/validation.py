"""Auth context, request body shape validation, and pagination.

Implements rungs 1-2 of the PRD section 2.6 validation ladder plus the
field-shape checks (ERR_INVALID_REQUEST) that the PRD evaluates independently
of the ladder.
"""
from flask import request

import store
from errors import err

ROLES = (
    "AssociationAdmin",
    "JurisdictionRegistrar",
    "CertificationEngineer",
    "FederalVerifier",
    "AuditAuthority",
)
ALL_ROLES = set(ROLES)

BRANDS = ("SALVAGE", "FLOOD", "REBUILT", "JUNK")


def auth_context():
    """Rung 1: X-User-ID and X-User-Role must be present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID header missing or malformed")
    if role is None or not str(role).strip():
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-Role header missing or malformed")
    return user_id, role


def require_role(role, allowed):
    """Rung 2: the declared role must be among the endpoint's roles."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "role %s may not perform this operation" % role)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _invalid(msg):
    return err("ERR_INVALID_REQUEST", msg)


def req_string(data, name):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _invalid("field '%s' is required and must be a non-empty string" % name)
    return value


def req_enum(data, name, members):
    value = data.get(name)
    if value not in members:
        raise _invalid("field '%s' must be one of %s" % (name, sorted(members)))
    return value


def req_int(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid("field '%s' is required and must be an integer" % name)
    if minimum is not None and value < minimum:
        raise _invalid("field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise _invalid("field '%s' must be <= %s" % (name, maximum))
    return value


def opt_int(data, name, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return None
    return req_int(data, name, minimum, maximum)


def req_date(data, name):
    value = data.get(name)
    try:
        return store.parse_date(value)
    except (ValueError, TypeError):
        raise _invalid("field '%s' must be an ISO date (YYYY-MM-DD)" % name)


def req_datetime(data, name):
    value = data.get(name)
    try:
        return store.parse_datetime(value)
    except (ValueError, TypeError):
        raise _invalid("field '%s' must be an ISO 8601 datetime" % name)


def req_brand_list(data, name, required):
    if name not in data or data[name] is None:
        if required:
            raise _invalid("field '%s' is required" % name)
        return []
    value = data[name]
    if not isinstance(value, list):
        raise _invalid("field '%s' must be an array" % name)
    out = []
    for item in value:
        if item not in BRANDS:
            raise _invalid("field '%s' contains an unknown brand" % name)
        if item not in out:
            out.append(item)
    return out


def parse_pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        raise _invalid("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise _invalid("offset must be an integer")
    if limit < 1 or limit > 100:
        raise _invalid("limit must be between 1 and 100")
    if offset < 0:
        raise _invalid("offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def registrar_jurisdiction(user_id):
    """Resolve the caller's own Jurisdiction for JurisdictionRegistrar
    endpoints (X-User-ID is the Jurisdiction id per PRD section 2.1)."""
    jurisdiction = store.db.jurisdictions.get(user_id)
    if jurisdiction is None:
        raise err("ERR_JURISDICTION_NOT_FOUND",
                  "caller jurisdiction %s not found" % user_id)
    return jurisdiction
