"""Ladder steps 1-6: auth, role, path existence, body shape, body foreign keys."""
from flask import request

from core import ROLES, fail, parse_dt, store

# --------------------------------------------------------- steps 1, 2 and 3 --
def auth(allowed_roles):
    """Returns (user_id, role). Raises the ladder's first three failures."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "" or role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role headers are required.")
    role = role.strip()
    user_id = user_id.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised role '%s'." % role)
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


# ------------------------------------------------------------------ step 4 --
_NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "cranes": "ERR_CRANE_NOT_FOUND",
    "personnel": "ERR_PERSONNEL_NOT_FOUND",
    "rigging_gear": "ERR_GEAR_NOT_FOUND",
    "lift_plans": "ERR_LIFT_PLAN_NOT_FOUND",
    "gear_assignments": "ERR_GEAR_ASSIGNMENT_NOT_FOUND",
    "engineering_reviews": "ERR_REVIEW_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "standby_events": "ERR_STANDBY_EVENT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
}


def must_exist(collection_name, row_id):
    rec = getattr(store, collection_name).get(row_id)
    if rec is None:
        fail(_NOT_FOUND[collection_name], "%s does not exist." % row_id)
    return rec


# ------------------------------------------------------------------ step 5 --
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


class Body(object):
    """Typed reader over a request body; every failure is ERR_INVALID_REQUEST."""

    def __init__(self, payload):
        self.p = payload

    def _present(self, name, required, default):
        if name not in self.p or self.p[name] is None:
            if required:
                _bad(name, "is required")
            return False, default
        return True, None

    def string(self, name, required=True, default=None, allow_empty=False):
        have, dflt = self._present(name, required, default)
        if not have:
            return dflt
        v = self.p[name]
        if not isinstance(v, str):
            _bad(name, "must be a string")
        if not allow_empty and v.strip() == "":
            _bad(name, "must be a non-empty string")
        return v

    def enum(self, name, members, required=True, default=None):
        have, dflt = self._present(name, required, default)
        if not have:
            return dflt
        v = self.p[name]
        if not isinstance(v, str) or v not in members:
            _bad(name, "must be one of %s" % ", ".join(members))
        return v

    def boolean(self, name, required=True, default=None):
        have, dflt = self._present(name, required, default)
        if not have:
            return dflt
        v = self.p[name]
        if not isinstance(v, bool):
            _bad(name, "must be a boolean")
        return v

    def integer(self, name, required=True, default=None, minimum=None, maximum=None,
                exclusive_min=None, choices=None):
        have, dflt = self._present(name, required, default)
        if not have:
            return dflt
        v = self.p[name]
        if not _is_int(v):
            _bad(name, "must be an integer")
        if minimum is not None and v < minimum:
            _bad(name, "must be at least %s" % minimum)
        if exclusive_min is not None and v <= exclusive_min:
            _bad(name, "must be greater than %s" % exclusive_min)
        if maximum is not None and v > maximum:
            _bad(name, "must be at most %s" % maximum)
        if choices is not None and v not in choices:
            _bad(name, "must be one of %s" % choices)
        return v

    def number(self, name, required=True, default=None, minimum=None, exclusive_min=None):
        have, dflt = self._present(name, required, default)
        if not have:
            return dflt
        v = self.p[name]
        if not _is_num(v):
            _bad(name, "must be a number")
        if minimum is not None and v < minimum:
            _bad(name, "must be at least %s" % minimum)
        if exclusive_min is not None and v <= exclusive_min:
            _bad(name, "must be greater than %s" % exclusive_min)
        return float(v)

    def datetime(self, name, required=True, default=None):
        """Returns (raw_string, parsed_datetime)."""
        have, dflt = self._present(name, required, default)
        if not have:
            return dflt, None
        v = self.p[name]
        parsed = parse_dt(v)
        if parsed is None:
            _bad(name, "must be an ISO 8601 UTC timestamp")
        return v, parsed


# ------------------------------------------------ step 5 (query parameters) --
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (ValueError, TypeError):
            _bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (ValueError, TypeError):
            _bad("offset", "must be a non-negative integer")
        if offset < 0:
            _bad("offset", "must be at least 0")
    return limit, offset


def q_enum(name, members):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in members:
        _bad(name, "must be one of %s" % ", ".join(members))
    return v


def q_str(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v


def q_bool(name):
    v = request.args.get(name)
    if v is None:
        return None
    low = str(v).strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    _bad(name, "must be true or false")


def q_int(name):
    v = request.args.get(name)
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        _bad(name, "must be an integer")


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serializer(r) for r in page], limit, offset, total


# ------------------------------------------------------------------ step 6 --
def fk(collection_name, row_id):
    """Body-supplied foreign key resolution (same catalogue as path ids)."""
    return must_exist(collection_name, row_id)
