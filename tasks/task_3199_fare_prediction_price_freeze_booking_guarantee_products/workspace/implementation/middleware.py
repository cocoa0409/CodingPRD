"""Auth, role entitlement, ownership and request-shape helpers.

PRD §2.1: two mandatory headers, `X-User-ID` and `X-User-Role`. Both must be
present and syntactically valid, and the role must be one of the six declared
roles — otherwise ERR_MISSING_OR_INVALID_CONTEXT_HEADER (400). A valid role
that is not entitled to the operation is ERR_FORBIDDEN_FOR_ACTOR (403).

Every one of the six roles is opaque: no role is backed by a persisted entity,
so `X-User-ID` is never compared against an entity `id`. Traveler ownership is
enforced against Itinerary.traveler_user_id instead (PRD §2.1, §2.6).
"""

from flask import g, request

from db import DB, parse_iso
from errors import fail

ROLES = (
    "Traveler", "OpsAgent", "RiskAnalyst", "ClaimsAdjuster",
    "PlatformAdmin", "SystemOperator",
)

IDENTITY_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def actor():
    """Priority 1 + 2: resolve and validate the acting identity and role."""
    user_id = request.headers.get(IDENTITY_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
             "X-User-ID and X-User-Role headers are both required")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
             "X-User-Role names an undeclared role")
    g.actor_id = user_id
    g.actor_role = role
    return user_id, role


def require_role(allowed):
    """Priority 2: the acting role must be listed on the endpoint."""
    user_id, role = actor()
    if role not in allowed:
        fail("ERR_FORBIDDEN_FOR_ACTOR",
             "role %s is not entitled to this operation" % role)
    return user_id, role


def require_owner(itinerary):
    """Priority 2/9: a Traveler owns the itinerary via traveler_user_id."""
    if itinerary["traveler_user_id"] != g.actor_id:
        fail("ERR_FORBIDDEN_FOR_ACTOR",
             "the acting traveler does not own this itinerary")
    return True


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def field(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "missing required field: %s" % name)
        return default
    return data[name]


def as_str(data, name, required=True, default=None):
    value = field(data, name, required, default)
    if value is None:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "field %s must be a string" % name)
    return value


def as_int(data, name, required=True, default=None):
    value = field(data, name, required, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "field %s must be an integer" % name)
    return value


def as_num(data, name, required=True, default=None):
    value = field(data, name, required, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "field %s must be a number" % name)
    return value


def as_bool(data, name, required=True, default=None):
    value = field(data, name, required, default)
    if value is None:
        return None
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "field %s must be a boolean" % name)
    return value


def as_ts(data, name, required=True, default=None):
    value = field(data, name, required, default)
    if value is None:
        return None
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "field %s is not a parseable ISO 8601 timestamp" % name)


def as_enum(data, name, allowed, required=True, default=None):
    value = as_str(data, name, required, default)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "field %s is not a member of %s" % (name, allowed))
    return value


def as_int_array(data, name, length=None, required=True, default=None):
    value = field(data, name, required, default)
    if value is None:
        return None
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "field %s must be an array" % name)
    if length is not None and len(value) != length:
        fail("ERR_INVALID_REQUEST", "field %s must have exactly %d entries" % (name, length))
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            fail("ERR_INVALID_REQUEST", "field %s must contain integers" % name)
    return value


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = PAGINATION_DEFAULT_LIMIT if limit_raw in (None, "") else int(limit_raw)
        offset = PAGINATION_DEFAULT_OFFSET if offset_raw in (None, "") else int(offset_raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit and offset must be integers")
    if limit < PAGINATION_MIN_LIMIT:
        limit = PAGINATION_MIN_LIMIT
    if limit > PAGINATION_MAX_LIMIT:
        limit = PAGINATION_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def page(items, limit, offset):
    return items[offset:offset + limit]


def owned_itinerary(itinerary_id, role_aware=True):
    """Resolve an itinerary and enforce Traveler ownership when applicable."""
    itinerary = DB.itineraries.get(itinerary_id)
    if itinerary is None:
        fail("ERR_ITINERARY_NOT_FOUND", "no itinerary %s" % itinerary_id)
    if role_aware and g.actor_role == "Traveler":
        require_owner(itinerary)
    return itinerary