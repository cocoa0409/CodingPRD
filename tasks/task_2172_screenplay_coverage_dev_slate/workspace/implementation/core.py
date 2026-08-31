"""Core infrastructure: errors, response envelope, logical clock, in-memory store,
auth/RBAC, request validation helpers, pagination."""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLES = (
    "SlateAdmin",
    "StoryEditor",
    "Submitter",
    "Reader",
    "BusinessAffairs",
    "DevelopmentExec",
    "Writer",
    "CommitteeMember",
)

# --------------------------------------------------------------------------
# Error catalogue
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_RELEASE_FORM_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_READER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_BOARD_ENTRY_NOT_FOUND": 404,
    "ERR_OPTION_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_WRITER_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_VALUE_OUT_OF_RANGE": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_TERMINAL_STATE": 409,
    "ERR_RELEASE_FORM_REQUIRED": 409,
    "ERR_RELEASE_FORM_EXPIRED": 409,
    "ERR_RIGHTS_CHAIN_INCOMPLETE": 409,
    "ERR_PROPERTY_RIGHTS_DISPUTED": 409,
    "ERR_OPTION_NOT_ACTIVE": 409,
    "ERR_OPTION_MISMATCH": 409,
    "ERR_OPTION_EXPIRED": 409,
    "ERR_OPTION_PERIOD_OVERLAP": 409,
    "ERR_RIGHTS_NOT_OWNED": 409,
    "ERR_READER_WINDOW_CONFLICT": 409,
    "ERR_READER_AT_CAPACITY": 409,
    "ERR_NO_ELIGIBLE_READER": 409,
    "ERR_WRITER_OVERCOMMITTED": 409,
    "ERR_COVERAGE_INCOMPLETE": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_COMMITTEE_TOO_SMALL": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_MILESTONE_SEQUENCE_VIOLATION": 409,
    "ERR_BUDGET_EXCEEDED": 409,
    "ERR_GUILD_MINIMUM_VIOLATION": 422,
    "ERR_TURNAROUND_NOT_MATURE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()}


def _clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": _clean(data)}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": [_clean(r) for r in rows]}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Numbers / time
# --------------------------------------------------------------------------
def round_half_up(value, places=2):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def dec(value):
    return Decimal(str(value))


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(text, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(text, str):
        fail(error_id)
    raw = text.strip()
    try:
        candidate = raw
        if candidate.endswith("Z") or candidate.endswith("z"):
            candidate = candidate[:-1] + "+00:00"
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        fail(error_id)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(text, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(text, str):
        fail(error_id)
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except Exception:
        fail(error_id)
        return None


def add_months(instant, months):
    """Advance by whole calendar months, clamping day-of-month, preserving time."""
    month_index = instant.month - 1 + months
    year = instant.year + month_index // 12
    month = month_index % 12 + 1
    day = instant.day
    while True:
        try:
            return instant.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


# --------------------------------------------------------------------------
# Logical clock + in-memory store
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "properties",
    "documents",
    "submissions",
    "release_forms",
    "readers",
    "assignments",
    "reports",
    "board_entries",
    "options",
    "projects",
    "writers",
    "engagements",
    "milestones",
    "reviews",
    "members",
    "votes",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock_raw = DEFAULT_CLOCK_UTC
        self.clock_dt = parse_dt(DEFAULT_CLOCK_UTC)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.clock_dt


def now_str():
    return fmt_dt(db.clock_dt)


def new_row(collection, fields, versioned=True):
    stamp = now_str()
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    getattr(db, collection)[row["id"]] = row
    return row


def touch(row):
    if row is None:
        return
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now_str()


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


def collection_rows(collection):
    return sort_rows(list(getattr(db, collection).values()))


def lookup(collection, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(error_id)
    return row


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if not role or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


# --------------------------------------------------------------------------
# Request body validation (rungs 5/6/7 of the rejection ladder)
# --------------------------------------------------------------------------
_MISSING = object()


def json_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


class Field(object):
    def __init__(self, name, kind, required=False, default=None,
                 enum=None, lo=None, hi=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.lo = lo
        self.hi = hi


def _type_ok(kind, value):
    if kind == "string" or kind == "enum" or kind == "datetime" or kind == "date":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    return True


def parse_fields(body, fields):
    """Three ordered passes: shape (400), enum (422), range (422)."""
    raw = {}
    # pass 1 - presence and declared JSON type
    for field in fields:
        value = body.get(field.name, _MISSING)
        if value is _MISSING or value is None:
            if field.required:
                fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field.name)
            raw[field.name] = _MISSING
            continue
        if not _type_ok(field.kind, value):
            fail("ERR_INVALID_REQUEST", "Field '%s' has the wrong type." % field.name)
        raw[field.name] = value
    # pass 2 - enums
    for field in fields:
        value = raw[field.name]
        if value is _MISSING or field.enum is None:
            continue
        if value not in field.enum:
            fail("ERR_INVALID_ENUM_VALUE", "Field '%s' is not a declared member." % field.name)
    # pass 3 - numeric ranges
    for field in fields:
        value = raw[field.name]
        if value is _MISSING or field.kind not in ("integer", "number"):
            continue
        if field.lo is not None and value < field.lo:
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is below its declared bound." % field.name)
        if field.hi is not None and value > field.hi:
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is above its declared bound." % field.name)
    out = {}
    for field in fields:
        value = raw[field.name]
        out[field.name] = field.default if value is _MISSING else value
    return out


# --------------------------------------------------------------------------
# Pagination + filtering
# --------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(str(limit_raw).strip())
        except Exception:
            fail("ERR_VALUE_OUT_OF_RANGE", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_VALUE_OUT_OF_RANGE", "limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(str(offset_raw).strip())
        except Exception:
            fail("ERR_VALUE_OUT_OF_RANGE", "offset must be an integer of at least 0.")
        if offset < 0:
            fail("ERR_VALUE_OUT_OF_RANGE", "offset must be at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def qp(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qp_bool(name):
    value = qp(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None


def qp_int(name):
    value = qp(name)
    if value is None:
        return None
    try:
        return int(value.strip())
    except Exception:
        return _MISSING


def filter_eq(rows, field, value):
    if value is None:
        return rows
    if value is _MISSING:
        return []
    return [r for r in rows if r.get(field) == value]
