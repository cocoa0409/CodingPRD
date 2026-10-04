"""Shared helpers: envelope, errors, auth, parsing, pagination, serialization."""

import random
import re
import string
import uuid
from datetime import date, datetime, timezone

from flask import jsonify, request

from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    ROLES,
)
from storage import STORE


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
    raise ApiError(error_id, http_status, message)


def validation(message):
    err("ERR_VALIDATION", 400, message)


def not_found(message="Resource not found"):
    err("ERR_NOT_FOUND", 404, message)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _wall_stamp():
    return iso_z(datetime.now(timezone.utc))


def envelope_meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, status=200):
    body = {
        "meta": envelope_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, page_meta):
    body = {
        "meta": envelope_meta(page_meta),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(e):
    body = {
        "meta": envelope_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Time formatting / parsing
# ---------------------------------------------------------------------------

def iso_z(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    """Strict YYYY-MM-DD -> date, else None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        return None


def parse_dt(s):
    """ISO 8601 timestamp -> aware UTC datetime, else None. Requires a time part."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if "T" not in t and " " not in t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def now():
    return STORE.now()


def today():
    return STORE.now().date()


def add_months(dt, months):
    """Calendar-month addition with day clamping (e.g. Jan 31 + 1 -> Feb 28/29)."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def fmt_val(v):
    if isinstance(v, datetime):
        return iso_z(v)
    if isinstance(v, list):
        return [fmt_val(x) for x in v]
    if isinstance(v, dict):
        return {k: fmt_val(x) for k, x in v.items()}
    return v


def serialize(entity):
    """Public view: drop internal '_' fields, format nested datetimes."""
    return {k: fmt_val(v) for k, v in entity.items() if not k.startswith("_")}


def bump(entity):
    """Every mutation of a resource increments version by exactly one."""
    entity["version"] += 1
    entity["updated_at"] = now()


def new_id():
    return str(uuid.uuid4())


def base_entity():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": STORE.next_seq(),
    }


# ---------------------------------------------------------------------------
# Auth (PRD 2.1): headers X-User-ID / X-User-Role always required
# ---------------------------------------------------------------------------

def authn():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown identity headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")


# ---------------------------------------------------------------------------
# Request body field validators (PRD 2.7 priority 3: request shape)
# ---------------------------------------------------------------------------

def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        validation(f"Field '{name}' is required and must be a non-empty string")
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        validation(f"Field '{name}' must be a string")
    return v


def req_int(b, name, minimum=None, maximum=None):
    v = b.get(name)
    if not _is_int(v):
        validation(f"Field '{name}' is required and must be an integer")
    if minimum is not None and v < minimum:
        validation(f"Field '{name}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        validation(f"Field '{name}' must be <= {maximum}")
    return v


def opt_int(b, name, default=None, minimum=None, maximum=None):
    v = b.get(name)
    if v is None:
        return default
    if not _is_int(v):
        validation(f"Field '{name}' must be an integer")
    if minimum is not None and v < minimum:
        validation(f"Field '{name}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        validation(f"Field '{name}' must be <= {maximum}")
    return v


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        validation(f"Field '{name}' is required and must be a boolean")
    return v


def opt_bool(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        validation(f"Field '{name}' must be a boolean")
    return v


def req_enum(b, name, values):
    v = b.get(name)
    if v not in values:
        validation(f"Field '{name}' must be one of {sorted(values)}")
    return v


def req_date(b, name):
    v = b.get(name)
    d = parse_date(v)
    if d is None:
        validation(f"Field '{name}' must be a well-formed YYYY-MM-DD date")
    return d


def req_datetime(b, name):
    v = b.get(name)
    d = parse_dt(v)
    if d is None:
        validation(f"Field '{name}' must be a well-formed ISO 8601 timestamp")
    return d


def req_number(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        validation(f"Field '{name}' is required and must be a number")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit 1..100 default 10, offset default 0,
# every list sorted by created_at ascending.
# ---------------------------------------------------------------------------

def _strict_int(raw):
    if raw is None:
        return None
    try:
        return int(raw, 10)
    except (ValueError, TypeError):
        return "BAD"


def paginate(items, serializer=None):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT if raw_limit is None else _strict_int(raw_limit)
    offset = PAGINATION_DEFAULT_OFFSET if raw_offset is None else _strict_int(raw_offset)
    if limit == "BAD" or limit is not None and not (PAGINATION_MIN_LIMIT <= limit <= PAGINATION_MAX_LIMIT):
        validation("limit must be an integer between 1 and 100")
    if offset == "BAD" or offset is not None and offset < 0:
        validation("offset must be an integer >= 0")
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    ser = serializer if serializer is not None else serialize
    return [ser(e) for e in page], meta


# ---------------------------------------------------------------------------
# Existence helpers (PRD 2.7 priority 4, path left-to-right)
# ---------------------------------------------------------------------------

def get_center(cid):
    c = STORE.centers.get(cid)
    if c is None:
        not_found("Center not found")
    return c


def get_agreement(aid):
    a = STORE.agreements.get(aid)
    if a is None:
        not_found("SiteAgreement not found")
    return a


def get_volunteer(vid):
    v = STORE.volunteers.get(vid)
    if v is None:
        not_found("Volunteer not found")
    return v


def get_screening(sid):
    s = STORE.screenings.get(sid)
    if s is None:
        not_found("BackgroundScreening not found")
    return s


def get_shift(sid):
    s = STORE.shifts.get(sid)
    if s is None:
        not_found("Shift not found")
    return s


def get_assignment(aid):
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("ShiftAssignment not found")
    return a


def get_guest(gid):
    g = STORE.guests.get(gid)
    if g is None:
        not_found("Guest not found")
    return g


def get_checkin(cid):
    c = STORE.checkins.get(cid)
    if c is None:
        not_found("VisitCheckIn not found")
    return c


def get_booking(bid):
    b = STORE.bookings.get(bid)
    if b is None:
        not_found("ServiceBooking not found")
    return b


def get_lot(lid):
    l = STORE.lots.get(lid)
    if l is None:
        not_found("DonationLot not found")
    return l


def get_event(eid):
    e = STORE.events.get(eid)
    if e is None:
        not_found("Event not found")
    return e
