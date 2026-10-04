from flask import request
from errors import ApiError, bad_request
from db import parse_date

ALL_ROLES = {
    "SiteDirector",
    "ProgramManager",
    "StipendAdministrator",
    "SchoolLiaison",
    "CorpsMember",
    "Applicant",
}


def auth(allowed_roles):
    """Priority 1-2: header presence/well-formedness, then role admission.
    Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required")
    uid = uid.strip()
    role = role.strip()
    if not uid or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers must be non-empty")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Role %s is not authorized for this endpoint" % role)
    return uid, role


def forbid_role(msg="Role not permitted for this operation"):
    raise ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def not_owner(msg="Caller does not own this entity"):
    raise ApiError("ERR_NOT_ENTITY_OWNER", 403, msg)


def body():
    """Parse JSON object body. Malformed JSON / non-object -> ERR_INVALID_REQUEST.
    Absent body -> {} (missing-field errors surface downstream)."""
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data()
        if raw and raw.strip():
            bad_request("Malformed JSON body")
        return {}
    if not isinstance(data, dict):
        bad_request("JSON body must be an object")
    return data


def need(data, field):
    v = data.get(field)
    if v is None:
        bad_request("Missing required field: %s" % field)
    return v


def need_str(data, field):
    v = need(data, field)
    if not isinstance(v, str) or not v.strip():
        bad_request("Field %s must be a non-empty string" % field)
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def need_int(data, field):
    v = need(data, field)
    if not is_int(v):
        bad_request("Field %s must be an integer" % field)
    return v


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def need_date(data, field):
    v = need(data, field)
    try:
        parse_date(v)
    except ValueError:
        bad_request("Field %s must be a YYYY-MM-DD date" % field)
    return v


def opt_date(data, field):
    v = data.get(field)
    if v is None:
        return None
    try:
        parse_date(v)
    except ValueError:
        bad_request("Field %s must be a YYYY-MM-DD date" % field)
    return v


def need_enum(data, field, values):
    v = need(data, field)
    if v not in values:
        bad_request("Field %s must be one of %s" % (field, sorted(values)))
    return v


def paginate(items):
    """Items must already be filtered. Sorts by insertion order (created_at
    ascending) and applies limit/offset per the envelope spec."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            bad_request("offset must be >= 0")
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
