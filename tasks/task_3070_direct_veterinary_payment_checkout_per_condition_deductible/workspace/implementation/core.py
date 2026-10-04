"""Core plumbing: store, clock, ids, envelope, auth, pagination, validation."""
import secrets
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def fail(error_id, status, message):
    raise ApiError(error_id, status, message)


ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"

ROLES = {"PlatformAdmin", "RateFilingAdmin", "HospitalStaff", "ClaimsAdjuster", "PetOwner"}


# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.clock = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.seq = 0
        self.filings = {}
        self.hospitals = {}
        self.policies = {}
        self.records = {}
        self.conditions = {}
        self.claims = {}
        self.lines = {}
        self.payments = {}
        self.appeals = {}
        self.reports = {}


store = Store()


def tick():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(store.clock)


def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    try:
        if t.endswith(("Z", "z")):
            t = t[:-1] + "+00:00"
        d = datetime.fromisoformat(t)
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def round_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------


def new_entity():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": tick()}


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] = e.get("version", 1) + 1
    e["_seq"] = tick()


def public(e, fields):
    return {k: e.get(k) for k in fields}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _meta():
    rid = "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
    return {"api_request_id": rid, "api_request_timestamp": now_iso()}


def ok(data, status=200, page=None):
    body = {"meta": _meta(), "response_type": "array" if page is not None else "object", "data": data}
    if page is not None:
        body["meta"].update(page)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def err(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.status
    return resp


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def ctx():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        fail(ERR_AUTH, 400, "Missing or malformed X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(*roles):
    uid, role = ctx()
    if role not in roles:
        fail(ERR_UNAUTHORIZED, 403, "Role %s is not permitted for this operation" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            fail(ERR_INVALID_REQUEST, 400, "offset must be non-negative")
    total = len(items)
    page_items = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page_items, meta


def sort_items(items):
    return sorted(items, key=lambda e: (e.get("created_at") or "", e.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def req_field(data, name):
    v = data.get(name)
    if v is None:
        fail(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
    return v


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or v == "":
        fail(ERR_INVALID_REQUEST, 400, "Field %s must be a non-empty string" % name)
    return v


def req_int(data, name, minimum=None):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        fail(ERR_INVALID_REQUEST, 400, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        fail(ERR_INVALID_REQUEST, 400, "Field %s is below its minimum" % name)
    return v


def opt_version(data, name):
    """OCC version field: must be present and an integer."""
    v = data.get(name)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        fail(ERR_INVALID_REQUEST, 400, "Field %s must be an integer" % name)
    return v
