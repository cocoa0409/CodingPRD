"""Core infrastructure: errors, in-memory store, logical clock, envelope, auth."""

import copy
import random
import re
import string
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import g, jsonify, request

UTC = timezone.utc

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_BRAND_OFFICER = "BrandComplianceOfficer"
ROLE_ANALYST = "NutritionAnalyst"
ROLE_PUBLISHER = "MenuboardPublisher"
ROLE_REGULATOR = "StateRegulator"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_BRAND_OFFICER,
    ROLE_ANALYST,
    ROLE_PUBLISHER,
    ROLE_REGULATOR,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ---------------------------------------------------------------------------
# Error catalog (PRD section 5) -- 49 error identifiers.
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_SCOPE": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_BRAND_NOT_FOUND": 404,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_ESTABLISHMENT_NOT_FOUND": 404,
    "ERR_MENU_ITEM_NOT_FOUND": 404,
    "ERR_RECIPE_NOT_FOUND": 404,
    "ERR_NUTRITION_ANALYSIS_NOT_FOUND": 404,
    "ERR_DISCLOSURE_PACKET_NOT_FOUND": 404,
    "ERR_MENU_BOARD_NOT_FOUND": 404,
    "ERR_VARIANCE_REQUEST_NOT_FOUND": 404,
    "ERR_ENFORCEMENT_ACTION_NOT_FOUND": 404,
    "ERR_STALE_MENU_ITEM_VERSION": 412,
    "ERR_STALE_BRAND_VERSION": 412,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_BOARD_NOT_DRAFT": 409,
    "ERR_RECIPE_NOT_DRAFT": 409,
    "ERR_ANALYSIS_ALREADY_DECIDED": 409,
    "ERR_RECIPE_NOT_APPROVED": 409,
    "ERR_ACTION_STATE_INVALID": 409,
    "ERR_VARIANCE_STATE_INVALID": 409,
    "ERR_PACKET_NOT_DRAFT": 409,
    "ERR_SAME_USER_CERTIFICATION": 403,
    "ERR_BRAND_POSTURE_FROZEN": 409,
    "ERR_BRAND_NOT_COVERED": 409,
    "ERR_ITEM_BRAND_MISMATCH": 409,
    "ERR_DUPLICATE_LISTING": 409,
    "ERR_CHOICE_GROUP_INCONSISTENT": 400,
    "ERR_RECIPE_HAS_NO_BASE_COMPONENT": 409,
    "ERR_NO_PUBLISHED_PACKET": 409,
    "ERR_ALLERGEN_MATRIX_INCOMPLETE": 409,
    "ERR_CROSS_CONTACT_STATEMENT_REQUIRED": 409,
    "ERR_SUCCINCT_STATEMENT_MISMATCH": 409,
    "ERR_SODIUM_WARNING_ICON_REQUIRED": 409,
    "ERR_ITEM_CALORIES_UNDECLARED": 409,
    "ERR_INVALID_DATE_RANGE": 400,
    "ERR_BOARD_WINDOW_CONFLICT": 409,
    "ERR_VARIANCE_NOT_ALLOWED": 409,
    "ERR_VARIANCE_WINDOW_CONFLICT": 409,
    "ERR_INFO_ROUND_REQUIRED": 409,
    "ERR_CITATION_SHIELDED_BY_VARIANCE": 409,
    "ERR_OUTSTANDING_PENALTY": 402,
    "ERR_NO_STALE_LISTINGS": 409,
    "ERR_ITEM_NOT_TEMPORARY": 409,
    "ERR_UNIT_HAS_OPEN_ENFORCEMENT": 409,
}

NOT_FOUND_IDS = {
    "brand": "ERR_BRAND_NOT_FOUND",
    "jurisdiction": "ERR_JURISDICTION_NOT_FOUND",
    "establishment": "ERR_ESTABLISHMENT_NOT_FOUND",
    "menu_item": "ERR_MENU_ITEM_NOT_FOUND",
    "recipe": "ERR_RECIPE_NOT_FOUND",
    "analysis": "ERR_NUTRITION_ANALYSIS_NOT_FOUND",
    "packet": "ERR_DISCLOSURE_PACKET_NOT_FOUND",
    "board": "ERR_MENU_BOARD_NOT_FOUND",
    "variance": "ERR_VARIANCE_REQUEST_NOT_FOUND",
    "enforcement": "ERR_ENFORCEMENT_ACTION_NOT_FOUND",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = status if status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def not_found(kind, message=None):
    raise ApiError(NOT_FOUND_IDS[kind], message or ("%s not found" % kind))


# ---------------------------------------------------------------------------
# Timestamps and logical clock
# ---------------------------------------------------------------------------

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(?:([Zz])|([+-])(\d{2}):?(\d{2}))?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Return an aware UTC datetime, or None when the value is not an instant."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if m.group(9):
        sign = 1 if m.group(9) == "+" else -1
        offset = timedelta(hours=int(m.group(10)), minutes=int(m.group(11)))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    """Return a datetime.date for a strict YYYY-MM-DD string, else None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def wall_now():
    return datetime.now(UTC)


def wall_iso():
    return fmt_instant(wall_now())


class Clock(object):
    """Logical clock. Starts at 2026-08-01T00:00:00Z on every fresh boot."""

    def __init__(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

    def now(self):
        return self.current

    def iso(self):
        return fmt_instant(self.current)

    def today(self):
        return self.current.astimezone(UTC).date()

    def set(self, dt):
        self.current = dt.astimezone(UTC)


CLOCK = Clock()


# ---------------------------------------------------------------------------
# In-memory store.  Starts empty on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------

TABLE_NAMES = (
    "brands",
    "jurisdictions",
    "establishments",
    "menu_items",
    "recipes",
    "components",
    "analyses",
    "boards",
    "listings",
    "packets",
    "variances",
    "enforcements",
)

META_FIELDS = ("id", "created_at", "updated_at", "version", "_seq")


class Store(object):
    def __init__(self):
        self.seq = 0
        for name in TABLE_NAMES:
            setattr(self, name, {})

    def snapshot(self):
        return (self.seq, dict((n, copy.deepcopy(getattr(self, n))) for n in TABLE_NAMES))

    def restore(self, snap):
        self.seq = snap[0]
        for name in TABLE_NAMES:
            setattr(self, name, snap[1][name])


S = Store()
LOCK = threading.Lock()


def rows(table, versioned=True):
    """All rows of a table in insertion (created_at ascending) order."""
    return sorted(table.values(), key=lambda r: (r["created_at"], r["_seq"]))


def insert(table, fields, versioned=True):
    row = dict(fields)
    S.seq += 1
    row["id"] = str(uuid.uuid4())
    row["_seq"] = S.seq
    row["created_at"] = wall_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    table[row["id"]] = row
    g.fresh_rows.add(row["id"])
    return row


def _projection(row):
    return dict((k, v) for k, v in row.items() if k not in META_FIELDS)


def mark(row):
    """Register a row so that a real change bumps updated_at/version once."""
    if row is None or "version" not in row:
        return
    rid = row["id"]
    if rid in g.fresh_rows or rid in g.marked:
        return
    g.marked[rid] = (row, copy.deepcopy(_projection(row)))


def force_mark(row):
    """Register a row whose version the PRD bumps unconditionally."""
    if row is None or "version" not in row:
        return
    mark(row)
    g.forced.add(row["id"])


def commit_versions():
    """Apply one updated_at/version bump per changed row.  Returns the bumped rows."""
    bumped = {}
    if not getattr(g, "marked", None):
        return bumped
    stamp = wall_iso()
    for rid, (row, snap) in g.marked.items():
        if rid in g.forced or _projection(row) != snap:
            row["updated_at"] = stamp
            row["version"] = int(row.get("version", 0)) + 1
            bumped[rid] = row
    g.marked = {}
    g.forced = set()
    return bumped


def _patch_versions(node, bumped):
    """Reflect end-of-request version bumps in an already serialised payload."""
    if isinstance(node, dict):
        rid = node.get("id")
        if isinstance(rid, str) and rid in bumped and "version" in node:
            node["version"] = bumped[rid]["version"]
            if "updated_at" in node:
                node["updated_at"] = bumped[rid]["updated_at"]
        for value in node.values():
            _patch_versions(value, bumped)
    elif isinstance(node, list):
        for value in node:
            _patch_versions(value, bumped)


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# ---------------------------------------------------------------------------

_ID_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def envelope(data, status=200, pagination=None):
    _patch_versions(data, commit_versions())
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_envelope(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            fail("ERR_INVALID_PAGINATION", "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < DEFAULT_OFFSET:
            fail("ERR_INVALID_PAGINATION", "offset out of range")
    return limit, offset


def page(items, limit, offset, serializer):
    total = len(items)
    window = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return envelope([serializer(i) for i in window], 200, pagination)


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD section 2.1)
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    if user_id is None or user_id.strip() == "":
        fail("ERR_MISSING_AUTH", "X-User-ID header is required")
    role = request.headers.get(HEADER_USER_ROLE)
    if role is None or role.strip() == "" or role not in ALL_ROLES:
        fail("ERR_INVALID_ROLE", "X-User-Role header is not a recognised role")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def any_role():
    return authenticate(ALL_ROLES)


def require_scope(owner_id):
    """Ownership scoping for entity-backed roles (writes only)."""
    if owner_id is None:
        return
    if g.role in (ROLE_PLATFORM_ADMIN, ROLE_ANALYST):
        return
    if g.user_id != owner_id:
        fail("ERR_FORBIDDEN_SCOPE", "caller is not scoped to this resource")


def body_or_empty():
    data = request.get_json(silent=True, force=True)
    if isinstance(data, dict):
        return data
    return {}


def get_body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        if not request.get_data():
            return {}
        fail("ERR_VALIDATION", "request body must be a JSON object")
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return data
