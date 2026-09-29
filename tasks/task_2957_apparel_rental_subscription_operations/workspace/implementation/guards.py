"""Validation ladder helpers: ranks 1-11 plus generic shape validation."""
from flask import request

from core import (DB, ApiError, ROLES, fail, is_date_str, parse_instant)


class Ctx(object):
    __slots__ = ("user_id", "role", "member", "technician")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.member = None
        self.technician = None


def _header(name):
    v = request.headers.get(name)
    if v is None:
        return None
    return v.strip()


def begin(allowed_roles):
    """Ranks 1-4: auth headers, known role, actor existence, role permitted."""
    uid = _header("X-User-ID")
    role = _header("X-User-Role")
    # Rank 1
    if not uid or not role:
        fail("ERR_MISSING_AUTH_HEADERS",
             "X-User-ID and X-User-Role headers are required")
    # Rank 2
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unknown role: %s" % role)
    ctx = Ctx(uid, role)
    # Rank 3 — entity-backed roles must resolve
    if role == "Member":
        ctx.member = DB["members"].get(uid)
        if ctx.member is None:
            fail("ERR_ACTOR_NOT_FOUND", "Acting member does not exist")
    elif role == "WarehouseTech":
        ctx.technician = DB["technicians"].get(uid)
        if ctx.technician is None:
            fail("ERR_ACTOR_NOT_FOUND", "Acting technician does not exist")
    # Rank 4
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED",
             "Role %s may not perform this operation" % role)
    return ctx


def require_own_member_id(ctx, member_id):
    """Rank 5 for endpoints whose path carries the member id directly."""
    if ctx.role == "Member" and member_id != ctx.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Members may only act on their own resources")


def require_owner(ctx, owner_member_id):
    """Rank 5 for resources that carry a member_id field."""
    if ctx.role == "Member" and owner_member_id != ctx.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Members may only act on their own resources")


def lookup(collection, ident, error_id):
    """Rank 6/7 resolution helper."""
    if not isinstance(ident, str):
        fail(error_id)
    row = DB[collection].get(ident)
    if row is None:
        fail(error_id)
    return row


# ---------------------------------------------------------------------------
# Body handling
# ---------------------------------------------------------------------------
def body_json():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return parsed


def fk(body, field, collection, error_id, required=False):
    """Rank 7: resolve a body foreign key when it is present and well typed."""
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str):
        return None  # shape problem, reported at rank 8
    row = DB[collection].get(value)
    if row is None:
        fail(error_id)
    return row


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s" % (field, why))


def validate(body, spec):
    """Two-pass shape (rank 8) then enum (rank 9) validation.

    Each spec entry is a dict with keys:
      name, kind, required (default False), default,
      min/max (ints), minlen/maxlen (strings), values (enums), charset
    """
    out = {}
    # ---- Rank 8: presence, JSON type, format / range constraints
    for f in spec:
        name = f["name"]
        kind = f["kind"]
        present = name in body and body[name] is not None
        if not present:
            if f.get("required"):
                _bad(name, "is required")
            if "default" in f:
                out[name] = f["default"]
            continue
        value = body[name]
        if kind in ("str", "enum", "date", "instant", "id"):
            if not isinstance(value, str):
                _bad(name, "must be a string")
            if kind == "date" and not is_date_str(value):
                _bad(name, "must be an ISO date (YYYY-MM-DD)")
            if kind == "instant" and parse_instant(value) is None:
                _bad(name, "must be an ISO-8601 UTC timestamp")
            if kind in ("str", "enum", "id"):
                lo = f.get("minlen")
                hi = f.get("maxlen")
                if lo is not None and len(value) < lo:
                    _bad(name, "must be at least %d characters" % lo)
                if hi is not None and len(value) > hi:
                    _bad(name, "must be at most %d characters" % hi)
                charset = f.get("charset")
                if charset and not all(c in charset for c in value):
                    _bad(name, "contains disallowed characters")
        elif kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                _bad(name, "must be an integer")
            if f.get("min") is not None and value < f["min"]:
                _bad(name, "must be >= %d" % f["min"])
            if f.get("max") is not None and value > f["max"]:
                _bad(name, "must be <= %d" % f["max"])
        elif kind == "bool":
            if not isinstance(value, bool):
                _bad(name, "must be a boolean")
        elif kind == "enum_list":
            if not isinstance(value, list):
                _bad(name, "must be an array")
            if f.get("non_empty") and len(value) == 0:
                _bad(name, "must be a non-empty array")
            for item in value:
                if not isinstance(item, str):
                    _bad(name, "must be an array of strings")
        else:
            raise ApiError("ERR_INTERNAL", "unknown spec kind %s" % kind)
        out[name] = value

    # ---- Rank 9: enum membership
    for f in spec:
        name = f["name"]
        if name not in out or out[name] is None:
            continue
        if f["kind"] == "enum" and f.get("values") is not None:
            if out[name] not in f["values"]:
                fail("ERR_INVALID_ENUM_VALUE",
                     "Field '%s' must be one of %s" % (name, ", ".join(f["values"])))
        elif f["kind"] == "enum_list" and f.get("values") is not None:
            for item in out[name]:
                if item not in f["values"]:
                    fail("ERR_INVALID_ENUM_VALUE",
                         "Field '%s' entries must be one of %s"
                         % (name, ", ".join(f["values"])))
    return out


# ---------------------------------------------------------------------------
# Query handling
# ---------------------------------------------------------------------------
def enum_query(name, values):
    """Rank 9 for enum-typed list filters."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        fail("ERR_INVALID_ENUM_VALUE",
             "Query parameter '%s' must be one of %s" % (name, ", ".join(values)))
    return raw


def str_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def bool_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean" % name)


def pagination():
    """Rank 10."""
    limit = 10
    offset = 0
    raw = request.args.get("limit")
    if raw is not None and raw != "":
        try:
            limit = int(raw)
        except Exception:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if str(limit) != raw.strip():
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    raw = request.args.get("offset")
    if raw is not None and raw != "":
        try:
            offset = int(raw)
        except Exception:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if str(offset) != raw.strip():
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset


def check_duplicate(collection, field, value, exclude_id=None):
    """Rank 11."""
    for row in DB[collection].values():
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row.get(field) == value:
            fail("ERR_DUPLICATE_CODE",
                 "%s '%s' is already in use" % (field, value))


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serializer(r) for r in page], total


def tech_active(ctx):
    """Rank 27: the acting technician's status must be ACTIVE."""
    if ctx.role == "WarehouseTech" and ctx.technician is not None:
        if ctx.technician["status"] != "ACTIVE":
            fail("ERR_TECHNICIAN_SUSPENDED", "The acting technician is SUSPENDED")


def tech_certified(ctx, flag):
    """Rank 26: the acting technician must carry the required certification."""
    tech = ctx.technician
    if tech is not None and not tech.get(flag):
        fail("ERR_TECHNICIAN_NOT_CERTIFIED",
             "The acting technician lacks the required certification")
