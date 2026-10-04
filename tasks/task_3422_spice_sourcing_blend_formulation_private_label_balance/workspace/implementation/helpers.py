"""Shared helpers: response envelope, request validation, auth, pagination,
exact-decimal and datetime utilities. All structural names (headers, envelope
fields, pagination params) follow SCAFFOLD.yaml / PRD.md exactly.
"""
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from functools import wraps

from flask import request, g, Response

from state import DB
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants pinned by SCAFFOLD.yaml / PRD.md
# ---------------------------------------------------------------------------
ROLE_NAMES = [
    "PlatformAdmin", "SupplyPlanner", "QualityAnalyst", "QualityManager",
    "FlavorScientist", "ProductionScheduler", "RecallCoordinator", "SupplierRep",
]
SPICE_CODES = ["BLACK_PEPPER", "PAPRIKA", "CUMIN", "OREGANO", "GARLIC_POWDER", "CINNAMON"]
ALLERGEN_PROFILES = ["NONE", "CELERY", "MUSTARD", "SESAME", "GLUTEN"]
CHANGEOVER_CLASSES = ["NONE", "DRY_CLEAN", "WET_WASH", "FULL_SANITATION"]
CERTIFICATIONS = ["ORGANIC", "KOSHER", "HALAL", "NON_GMO"]
TEST_TYPES = ["MICRO", "ADULTERANT_SCREEN", "PESTICIDE", "MOISTURE"]

MISSING = object()
Q3 = Decimal("0.001")
HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Exact decimal arithmetic (constants.DECIMAL_RULE: 3-decimal kg and integer
# cents, ROUND_HALF_UP; binary floating point forbidden inside calculations)
# ---------------------------------------------------------------------------
def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def q3(x):
    """Round half-up to 3 decimals."""
    return D(x).quantize(Q3, rounding=ROUND_HALF_UP)


def floor3(x):
    """Round down (floor) to 3 decimals — the per-line single-lot cap."""
    return D(x).quantize(Q3, rounding=ROUND_FLOOR)


def round_cents(x):
    """Round half-up to a whole cent, returned as int."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------
def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000,)


def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Expected an ISO8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid ISO8601 datetime: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp():
    """Logical-clock timestamp offset by a monotonic microsecond sequence so
    created_at stays strictly increasing in creation order."""
    return DB.clock + timedelta(microseconds=DB.next_seq())


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------
def new_entity(fields):
    e = dict(fields)
    e["id"] = str(uuid.uuid4())
    ts = stamp()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = DB.seq
    return e


def touch(e):
    """A mutation: version += 1, updated_at refreshed."""
    e["updated_at"] = stamp()
    e["version"] += 1


def pub(e):
    """Public view: strip internal keys."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


def json_safe(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime):
        return iso(o)
    raise TypeError("Not JSON serializable: %r" % (o,))


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope, verbatim structure)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": iso(stamp()),
    }


def respond(data, code=200, page=None):
    meta = _meta()
    if page is not None:
        meta.update(page)
        rtype = "array"
    else:
        rtype = "object"
    body = {"meta": meta, "response_type": rtype, "data": data}
    return Response(json.dumps(body, default=json_safe), status=code, mimetype="application/json")


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return Response(json.dumps(body), status=err.status, mimetype="application/json")


# ---------------------------------------------------------------------------
# Auth (PRD 2.1 / pipeline steps 1-2)
# ---------------------------------------------------------------------------
def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLE_NAMES:
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "Missing or invalid X-User-ID / X-User-Role headers")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", 403,
                               "Role %s is not permitted for this endpoint" % role)
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Request shape validation (pipeline step 3: ERR_INVALID_REQUEST / 400)
# ---------------------------------------------------------------------------
class F:
    """Body field spec. typ: str|int|num|bool|dt|enum|list."""

    def __init__(self, typ, required=False, default=MISSING, enum=None,
                 nullable=False, item_enum=None, item=None):
        self.typ = typ
        self.required = required
        self.default = default
        self.enum = set(enum) if enum else None
        self.nullable = nullable
        self.item_enum = set(item_enum) if item_enum else None
        self.item = item

    def convert(self, v, name):
        def bad():
            return ApiError("ERR_INVALID_REQUEST", 400,
                            "Field %r has an invalid value or type" % name)
        if self.typ == "str":
            if not isinstance(v, str):
                raise bad()
            return v
        if self.typ == "int":
            if not isinstance(v, int) or isinstance(v, bool):
                raise bad()
            return v
        if self.typ == "num":
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise bad()
            if isinstance(v, float) and not math.isfinite(v):
                raise bad()
            return D(v)
        if self.typ == "bool":
            if not isinstance(v, bool):
                raise bad()
            return v
        if self.typ == "dt":
            return parse_dt(v)
        if self.typ == "enum":
            if not isinstance(v, str) or v not in self.enum:
                raise bad()
            return v
        if self.typ == "list":
            if not isinstance(v, list):
                raise bad()
            if self.item_enum is not None:
                for x in v:
                    if not isinstance(x, str) or x not in self.item_enum:
                        raise bad()
            elif self.item == "str":
                for x in v:
                    if not isinstance(x, str):
                        raise bad()
            return list(v)
        raise AssertionError("unknown field type %r" % self.typ)


def validate_body(spec):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    unknown = set(body.keys()) - set(spec.keys())
    if unknown:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Unknown field(s): %s" % ", ".join(sorted(unknown)))
    out = {}
    for name, f in spec.items():
        if name not in body:
            if f.required:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Missing required field: %r" % name)
            out[name] = None if f.default is MISSING else (
                f.default() if callable(f.default) else f.default)
            continue
        v = body[name]
        if v is None:
            if f.nullable:
                out[name] = None
                continue
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field %r may not be null" % name)
        out[name] = f.convert(v, name)
    return out


# ---------------------------------------------------------------------------
# Error shortcuts (pipeline steps 4/5/7)
# ---------------------------------------------------------------------------
def validation_error(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def not_found(msg="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0;
# results sorted by created_at ascending)
# ---------------------------------------------------------------------------
def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paged(items):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = page_params()
    total = len(items)
    page_items = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [pub(e) for e in page_items], meta


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid value for filter %r" % name)
    return raw
