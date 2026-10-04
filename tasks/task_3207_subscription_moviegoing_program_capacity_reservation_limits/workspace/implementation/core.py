import os
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone

# ---------------- Constants ----------------
HOLD_TTL_MINUTES = 15
LOCK_MINUTES_BEFORE_START = 10
NO_SHOW_GRACE_MINUTES = 30
CANCELLATION_WINDOW_MINUTES = 30
STRIKE_WINDOW_DAYS = 90
SUSPENSION_THRESHOLD = 3
SUSPENSION_DAYS = 30
REJOIN_WAIT_DAYS = 30
FLAG_LEVEL = 2
POINTS_PER_DOLLAR = 20
ADMISSION_POINTS = 50
STUDIO_CONTRACT_RATE_CENTS = 899
DEFAULT_DISPLACEMENT_CAP_PCT = 40
WEEK_DAYS = 7
CYCLE_DAYS = 30
CHECKIN_EARLY_MINUTES = 45
CHECKIN_LATE_MINUTES = 30

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = {"ProgramAdmin", "MemberServices", "Member", "TheaterStaff", "StudioRep"}

MEMBER_STATUSES = ["REGISTERED", "ACTIVE", "SUSPENDED", "CLOSED"]
PLAN_STATUSES = ["DRAFT", "PUBLISHED", "RETIRED"]
SUB_STATUSES = ["ACTIVE", "PAUSED", "CANCELLED", "REJOIN_LOCKED"]
BUCKET_POSTURES = ["OPEN", "EXHAUSTED", "EXPIRED"]
THEATER_STATUSES = ["OPERATING", "DARK"]
FORMATS = ["STANDARD", "IMAX", "DOLBY", "THREE_D"]
SHOWTIME_STATUSES = ["SCHEDULED", "ON_SALE", "LOCKED", "COMPLETED", "CANCELLED"]
RESERVATION_STATUSES = ["HELD", "CONFIRMED", "CANCELLED", "NO_SHOW", "CHECKED_IN", "EXPIRED"]
STRIKE_STATUSES = ["ACTIVE", "EXPIRED", "REVERSED"]
LEDGER_KINDS = ["EARN_CONCESSION", "EARN_ADMISSION", "REDEEM", "EXPIRE", "ADJUST"]
REPORT_STATUSES = ["DRAFT", "SUBMITTED", "ACKNOWLEDGED", "DISPUTED"]
LINE_KINDS = ["SUBSCRIPTION", "PAID"]
TIERS = ["BASIC", "PLUS", "PREMIER"]

# ---------------- Store ----------------
STORE = {
    "members": {},
    "plans": {},
    "subscriptions": {},
    "buckets": {},
    "theaters": {},
    "auditoriums": {},
    "showtimes": {},
    "reservations": {},
    "strikes": {},
    "ledger": {},
    "purchases": {},
    "reports": {},
    "lines": {},
}

CLOCK = {"now": DEFAULT_CLOCK}


def now():
    return CLOCK["now"]


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------- Time helpers ----------------
def parse_dt(value):
    """Parse an ISO8601 datetime into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    return d.isoformat()


def wall_timestamp():
    return fmt_dt(datetime.now(timezone.utc))


# ---------------- Errors ----------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced entity does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Invalid request payload"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Resource not in a state permitting the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------- Envelope ----------------
def envelope_ok(data, response_type, status=200, pagination=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_timestamp()}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return body, status


def envelope_error(error_id, message, status):
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_timestamp()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return body, status


# ---------------- Entity helpers ----------------
def stamp_new(entity):
    ts = fmt_dt(now())
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_new_lean(entity):
    entity["id"] = new_id()
    entity["created_at"] = fmt_dt(now())
    return entity


def touch(entity):
    entity["updated_at"] = fmt_dt(now())
    entity["version"] = entity.get("version", 1) + 1


# ---------------- Auth ----------------
def get_auth(flask_request):
    user_id = flask_request.headers.get("X-User-ID")
    role = flask_request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_role(role, *allowed):
    if role not in allowed:
        raise err_forbidden()


def check_member_identity(user_id, role, member_id):
    """Priority-4 entity-backed identity: a Member acts only on own resources."""
    if role == "Member" and user_id != member_id:
        raise err_forbidden("Member may only act on their own resources")


# ---------------- Body validation ----------------
def parse_body(flask_request, schema):
    """schema: {field: (kind, required, enum_or_none)}.
    kind in {'str','int','bool','strlist','dt'}.
    Rejects unknown keys, missing required, type mismatch, enum violations."""
    body = flask_request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise err_invalid_request(f"Unknown payload key: {key}")
    out = {}
    for field, (kind, required, enum) in schema.items():
        if field not in body or body[field] is None:
            if required:
                raise err_invalid_request(f"Missing required field: {field}")
            out[field] = None
            continue
        val = body[field]
        if kind == "str":
            if not isinstance(val, str):
                raise err_invalid_request(f"Field {field} must be a string")
        elif kind == "int":
            if not isinstance(val, int) or isinstance(val, bool):
                raise err_invalid_request(f"Field {field} must be an integer")
        elif kind == "bool":
            if not isinstance(val, bool):
                raise err_invalid_request(f"Field {field} must be a boolean")
        elif kind == "strlist":
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise err_invalid_request(f"Field {field} must be an array of strings")
        elif kind == "dt":
            try:
                val = parse_dt(val)
            except (ValueError, TypeError):
                raise err_invalid_request(f"Field {field} must be an ISO8601 datetime")
        if enum is not None and val not in enum:
            raise err_invalid_request(f"Field {field} must be one of {enum}")
        out[field] = val
    return out


# ---------------- Pagination ----------------
def get_pagination(flask_request):
    raw_limit = flask_request.args.get("limit")
    raw_offset = flask_request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items: list sorted by created_at ascending. Returns (page, pagination_meta)."""
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return page, meta


# ---------------- Lookup helpers ----------------
def lookup(collection, entity_id, msg="Referenced entity does not exist"):
    ent = STORE[collection].get(entity_id)
    if ent is None:
        raise err_not_found(msg)
    return ent
