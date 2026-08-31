"""Core primitives: errors, response envelope, logical clock, in-memory store, auth."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Error catalogue (PRD §5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ASSOCIATION_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_LOCKBOX_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ENTITY_TERMINAL": 409,
    "ERR_MEMBER_NOT_ELIGIBLE": 409,
    "ERR_LOCKBOX_MISSING": 409,
    "ERR_CONTRACTOR_INSURANCE_EXPIRED": 409,
    "ERR_ASSOCIATION_FROZEN": 409,
    "ERR_ASSOCIATION_RESTRICTED": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_GRANT_WINDOW_TOO_LONG": 422,
    "ERR_GRANT_WINDOW_CONFLICT": 409,
    "ERR_SHOWING_CAPACITY_EXCEEDED": 409,
    "ERR_TEMP_CODE_LIMIT_REACHED": 409,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_DUPLICATE_MLS_NUMBER": 409,
    "ERR_LOCKBOX_NOT_ON_LISTING": 409,
    "ERR_SHOWING_NO_LOCKBOX": 409,
    "ERR_PLACEMENT_ALREADY_ACTIVE": 409,
    "ERR_MEMBER_BALANCE_DELINQUENT": 402,
    "ERR_CHARGE_NOT_ADJUSTABLE": 409,
    "ERR_EVIDENCE_LOCKED": 409,
    "ERR_RECOVERY_WINDOW_CLOSED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns a date, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def end_of_day(d):
    """A YYYY-MM-DD date read at 23:59:59.999Z (deadline being tested)."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def start_of_day(d):
    """A YYYY-MM-DD date read at 00:00:00.000Z (deadline being set)."""
    return datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def num2(value):
    """Round half up to two decimals and return a float for JSON output."""
    return float(round_half_up(value, 2))


# ---------------------------------------------------------------------------
# In-memory store (wiped on every process boot; never seeded)
# ---------------------------------------------------------------------------
class Store:
    COLLECTIONS = (
        "associations", "members", "contractors", "lockboxes", "listings",
        "placements", "credentials", "grants", "appointments", "events",
        "reviews", "charges",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_common(extra_ts=True):
    stamp = iso(now())
    rec = {"id": new_id(), "_seq": db.next_seq()}
    if extra_ts:
        rec["created_at"] = stamp
        rec["updated_at"] = stamp
        rec["version"] = 1
    else:
        rec["created_at"] = stamp
    return rec


def touch(rec):
    """Advance a versioned record: bump version, refresh updated_at."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = iso(now())
    return rec


def ordered(collection, records=None):
    src = list(records) if records is not None else list(collection.values())
    return sorted(src, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def access_code():
    return "".join(random.choice(string.digits) for _ in range(6))


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _meta():
    rid = "req_" + "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(20)
    )
    return {
        "api_request_id": rid,
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1) — ladder rungs 1 and 2
# ---------------------------------------------------------------------------
ROLES = ("AssociationAdmin", "Member", "SecurityAuditor", "LockboxDevice")

ADMIN = "AssociationAdmin"
MEMBER = "Member"
AUDITOR = "SecurityAuditor"
DEVICE = "LockboxDevice"

READ_ROLES = [ADMIN, MEMBER, AUDITOR]


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role headers are required.")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES or role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_str(value):
    return isinstance(value, str)


def present(payload, key):
    return key in payload and payload[key] is not None


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def qfilter(rows, field, arg=None):
    value = request.args.get(arg or field)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


# ---------------------------------------------------------------------------
# Path / body lookups (ladder rungs 3 and 4)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "associations": "ERR_ASSOCIATION_NOT_FOUND",
    "members": "ERR_MEMBER_NOT_FOUND",
    "contractors": "ERR_CONTRACTOR_NOT_FOUND",
    "lockboxes": "ERR_LOCKBOX_NOT_FOUND",
    "listings": "ERR_LISTING_NOT_FOUND",
    "placements": "ERR_PLACEMENT_NOT_FOUND",
    "credentials": "ERR_CREDENTIAL_NOT_FOUND",
    "grants": "ERR_GRANT_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "events": "ERR_EVENT_NOT_FOUND",
    "reviews": "ERR_REVIEW_NOT_FOUND",
    "charges": "ERR_CHARGE_NOT_FOUND",
}


def lookup(collection, ident, error_id=None):
    coll = getattr(db, collection)
    rec = coll.get(ident) if isinstance(ident, str) else None
    if rec is None:
        fail(error_id or _NOT_FOUND[collection])
    return rec


def lookup_fk(collection, payload, key):
    """Resolve an optional body foreign key. Missing/None -> None."""
    if not present(payload, key):
        return None
    return lookup(collection, payload[key])
