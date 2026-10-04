"""Core infrastructure: logical clock, in-memory store, envelope, auth, errors."""
import functools
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_EPOCH = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _EPOCH}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# In-memory store (dicts keyed by id). Starts empty on every boot.
# ---------------------------------------------------------------------------
DB = {
    "territories": {},
    "agents": {},
    "franchisees": {},
    "stores": {},
    "site_applications": {},
    "impact_studies": {},
    "protests": {},
    "transfer_requests": {},
    "enrollments": {},
    "mandates": {},
    "inspections": {},
    "promotions": {},
    "votes": {},
    "disputes": {},
    "fee_statements": {},
}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    try:
        base = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
        )
    except ValueError:
        return None
    frac = m.group(7)
    if frac:
        digits = frac[1:]
        micros = int((digits + "000000")[:6])
        base = base.replace(microsecond=micros)
    tzs = m.group(8)
    if tzs in (None, "Z"):
        return base.replace(tzinfo=timezone.utc)
    sign = 1 if tzs[0] == "+" else -1
    tzs2 = tzs[1:].replace(":", "")
    off = timedelta(hours=int(tzs2[:2]), minutes=int(tzs2[2:4]))
    return base.replace(tzinfo=timezone(timedelta(0) + sign * off)).astimezone(timezone.utc)


def request_ts():
    return fmt_dt(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": "req_" + uuid.uuid4().hex[:20],
         "api_request_timestamp": request_ts()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    has_more = (offset + len(items)) < total
    body = {
        "meta": _meta({"limit": limit, "offset": offset,
                       "total_count": total, "has_more": has_more}),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


# ---------------------------------------------------------------------------
# Auth / roles
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "FranchisorOps", "DevelopmentAgent",
         "Franchisee", "Mediator", "Inspector"}


def caller():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid == "" or role == "":
        raise err("ERR_UNAUTHENTICATED", 401,
                  "Missing or empty X-User-Role / X-User-ID headers")
    return uid, role


def require_roles(*roles):
    uid, role = caller()
    if role not in roles:
        raise err("ERR_UNAUTHORIZED_ROLE", 403,
                  f"Role {role} is not permitted on this endpoint")
    return uid, role


def forbid(message="Entity-backed ownership check failed"):
    raise err("ERR_UNAUTHORIZED_ROLE", 403, message)


# ---------------------------------------------------------------------------
# Body parsing and field validation
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def bad(message):
    raise err("ERR_INVALID_REQUEST", 400, message)


def req_field(data, name):
    if name not in data or data[name] is None:
        bad(f"Missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or v == "":
        bad(f"Field {name} must be a non-empty string")
    return v


def opt_str(data, name):
    v = data.get(name)
    if v is not None and not isinstance(v, str):
        bad(f"Field {name} must be a string")
    return v


def req_num(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad(f"Field {name} must be a number")
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        bad(f"Field {name} must be an integer")
    return v


def req_dt(data, name):
    v = req_field(data, name)
    dt = parse_dt(v)
    if dt is None:
        bad(f"Field {name} must be an ISO-8601 datetime")
    return dt


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        bad(f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be non-negative")
    return limit, offset


def paginate(records, serializer):
    """records: iterable of dicts with _seq; returns a list response."""
    limit, offset = pagination_params()
    items = sorted(records, key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def touch(obj):
    obj["version"] += 1
    # PRD §2.4: created_at/updated_at are server-side ISO 8601 UTC timestamps;
    # they track the wall clock, not the logical business clock of §2.6.
    obj["updated_at"] = datetime.now(timezone.utc)


def make_entity(kind):
    now = datetime.now(timezone.utc)
    return {"id": new_id(), "created_at": now, "updated_at": now,
            "version": 1, "_seq": next_seq(), "_kind": kind}


def base_fields(obj):
    return {"id": obj["id"], "created_at": fmt_dt(obj["created_at"]),
            "updated_at": fmt_dt(obj["updated_at"]), "version": obj["version"]}


def get_or_404(kind, entity_id, error_id):
    obj = DB[kind].get(entity_id)
    if obj is None:
        raise err(error_id, 404, f"{kind[:-1].replace('_', ' ')} not found")
    return obj


# ---------------------------------------------------------------------------
# Lazy time-driven transitions (applied on read / before each request)
# ---------------------------------------------------------------------------
def apply_lazy():
    now = clock_now()
    for e in list(DB["enrollments"].values()):
        if e["status"] == "ENROLLED" and now >= e["expires_on"]:
            e["status"] = "EXPIRED"
            touch(e)
            # Cascade: revert BUYER_TRAINING transfer requests to PENDING
            for tr in DB["transfer_requests"].values():
                if tr["buyer_franchisee_id"] == e["franchisee_id"] and \
                        tr["status"] == "BUYER_TRAINING":
                    tr["status"] = "PENDING"
                    touch(tr)
    for m in list(DB["mandates"].values()):
        if m["status"] in ("ISSUED", "SCHEDULED") and now >= m["due_by"]:
            m["status"] = "OVERDUE"
            touch(m)
