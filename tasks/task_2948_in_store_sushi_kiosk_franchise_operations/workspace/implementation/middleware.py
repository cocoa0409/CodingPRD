"""Authentication, role authorization, ownership and schema validation.

PRD 2.1 -- headers X-User-ID / X-User-Role, the four roles, identity binding.
PRD 2.6 -- rungs 1 (auth), 2 (role), 3 (ownership), 5 (schema).
"""

import json

from flask import g, request

import db
from core import dec, parse_date, parse_instant
from errors import ApiError

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ROLE_FRANCHISOR_OPS = "FranchisorOps"
ROLE_HOST_STORE_MANAGER = "HostStoreManager"
ROLE_FRANCHISE_CHEF = "FranchiseChef"
ROLE_QUALITY_AUDITOR = "QualityAuditor"

ALL_ROLES = (
    ROLE_FRANCHISOR_OPS,
    ROLE_HOST_STORE_MANAGER,
    ROLE_FRANCHISE_CHEF,
    ROLE_QUALITY_AUDITOR,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_manager(self):
        return self.role == ROLE_HOST_STORE_MANAGER

    @property
    def is_chef(self):
        return self.role == ROLE_FRANCHISE_CHEF


# --------------------------------------------------------------------------
# Rung 1 + 2
# --------------------------------------------------------------------------


def authorize(*roles):
    """Rung 1 (authentication) then rung 2 (role authorization)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    actor = Actor(user_id, role)
    g.actor = actor
    return actor


def current_user_id():
    actor = getattr(g, "actor", None)
    if actor is None:
        return None
    return actor.user_id


# --------------------------------------------------------------------------
# Rung 3 -- ownership (PRD 2.1)
# --------------------------------------------------------------------------


def own_store(actor, host_store_id):
    """A HostStoreManager's X-User-ID is the id of the acting HostStore."""
    if actor.is_manager and actor.user_id != host_store_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def own_kiosk(actor, kiosk_id):
    """A FranchiseChef's X-User-ID is the id of the acting Chef."""
    if not actor.is_chef:
        return
    chef = db.chefs.get(actor.user_id)
    if chef is None or chef.get("assigned_kiosk_id") != kiosk_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def acting_chef(actor):
    chef = db.chefs.get(actor.user_id)
    if chef is None:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return chef


# --------------------------------------------------------------------------
# Rung 5 -- schema (PRD 2.6)
# --------------------------------------------------------------------------


def body():
    """Parse the JSON request body. Absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def _present(payload, field, optional):
    if field not in payload or payload[field] is None:
        if optional:
            return False
        bad(field, "is required.")
    return True


def req_str(payload, field, optional=False, default=None, allow_blank=False):
    if not _present(payload, field, optional):
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad(field, "must be a string.")
    if not allow_blank and value.strip() == "":
        bad(field, "must not be blank.")
    return value


def req_enum(payload, field, allowed, optional=False, default=None):
    value = req_str(payload, field, optional=optional, default=None)
    if value is None:
        return default
    if value not in allowed:
        bad(field, "must be one of %s." % ", ".join(sorted(allowed)))
    return value


def req_bool(payload, field, optional=False, default=None):
    if not _present(payload, field, optional):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean.")
    return value


def req_int(payload, field, optional=False, default=None, minimum=None, maximum=None,
            exclusive_minimum=None):
    if not _present(payload, field, optional):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(field, "must be an integer.")
    _range(field, value, minimum, maximum, exclusive_minimum)
    return value


def req_num(payload, field, optional=False, default=None, minimum=None, maximum=None,
            exclusive_minimum=None):
    if not _present(payload, field, optional):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(field, "must be a number.")
    _range(field, value, minimum, maximum, exclusive_minimum)
    return dec(value)


def _range(field, value, minimum, maximum, exclusive_minimum):
    if minimum is not None and dec(value) < dec(minimum):
        bad(field, "must be greater than or equal to %s." % minimum)
    if exclusive_minimum is not None and dec(value) <= dec(exclusive_minimum):
        bad(field, "must be greater than %s." % exclusive_minimum)
    if maximum is not None and dec(value) > dec(maximum):
        bad(field, "must be less than or equal to %s." % maximum)


def req_instant(payload, field, optional=False, default=None):
    value = req_str(payload, field, optional=optional, default=None)
    if value is None:
        return default
    parsed = parse_instant(value)
    if parsed is None:
        bad(field, "must be a well-formed ISO 8601 instant.")
    return parsed


def req_date(payload, field, optional=False, default=None):
    value = req_str(payload, field, optional=optional, default=None)
    if value is None:
        return default
    parsed = parse_date(value)
    if parsed is None:
        bad(field, "must be a YYYY-MM-DD calendar date.")
    return value


def req_id(payload, field, optional=False, default=None):
    return req_str(payload, field, optional=optional, default=default)


def strictly_ordered(start_field, start, end_field, end):
    """PRD 2.6 rung 5: every start/end pair strictly ordered, start before end."""
    if start is not None and end is not None and not (start < end):
        bad(end_field, "must be strictly after %s." % start_field)


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def page_params():
    limit = _query_int("limit", PAGE_LIMIT_DEFAULT)
    offset = _query_int("offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        bad("limit", "must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if offset < 0:
        bad("offset", "must not be negative.")
    return limit, offset


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        bad(name, "must be an integer.")


def query(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def slice_rows(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
