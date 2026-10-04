"""Request hygiene: auth headers, RBAC, body parsing, pagination.

Header names and role names come from PRD.md §2.1; pagination parameter names and
bounds come from SCAFFOLD.yaml §1.5 `response_envelope.pagination_*` and PRD §2.3.
"""

from flask import request

from db import parse_iso
from errors import ApiError

# The nine role names, spelled exactly as PRD.md §2.1 fixes them.
GRANTABLE_ROLES = {
    "PlatformAdmin",
    "ProtocolCoordinator",
    "IRBReviewer",
    "IntakeCoordinator",
    "HousingCoordinator",
    "PatientSupportOfficer",
    "AffiliateClinicCoordinator",
    "SurvivorshipCoordinator",
    "Any",
}

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def user_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if not role or not str(role).strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    role = str(role).strip()
    if role not in GRANTABLE_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return {"user_id": str(user_id).strip(), "role": role}


def current_role():
    return user_context()["role"]


def require_role(*roles):
    """Auth first (header presence), then the RBAC matrix (priority 2).

    An operation declared for `Any` is reachable by every authenticated role
    (PRD §2.1); an operation declared for a specific role is exclusive to it.
    """
    context = user_context()
    role = context["role"]
    allowed = set()
    for entry in roles:
        if entry == "Any":
            allowed.update(GRANTABLE_ROLES)
        else:
            allowed.add(entry)
    if role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")
    return context


# --- body parsing ------------------------------------------------------------

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError("ERR_INVALID_REQUEST")
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return data


MISSING = object()


def required(data, field, kind=None):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return coerce(data[field], field, kind)


def optional(data, field, default=None, kind=None):
    if field not in data or data[field] is None:
        return default
    return coerce(data[field], field, kind)


def coerce(value, field, kind):
    if kind == "str":
        if not isinstance(value, str):
            raise ApiError("ERR_INVALID_REQUEST")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("ERR_INVALID_REQUEST")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise ApiError("ERR_INVALID_REQUEST")
        return value
    if kind == "list":
        if not isinstance(value, list):
            raise ApiError("ERR_INVALID_REQUEST")
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            raise ApiError("ERR_INVALID_REQUEST")
        try:
            parse_iso(value)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST")
        return value
    return value


def deep_get(data, field, kind):
    """For nested fields that are individually validated by hand."""
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return coerce(data[field], field, kind)


# --- pagination --------------------------------------------------------------

class Pagination(object):
    def __init__(self, limit, offset):
        self.limit = limit
        self.offset = offset

    def slice(self, items):
        return items[self.offset:self.offset + self.limit]


def pagination(has_limit=True):
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    if has_limit:
        raw_limit = request.args.get("limit")
        if raw_limit is not None and raw_limit != "":
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                raise ApiError("ERR_INVALID_REQUEST")
            if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
                raise ApiError("ERR_INVALID_REQUEST")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST")
    return Pagination(limit, offset)


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value