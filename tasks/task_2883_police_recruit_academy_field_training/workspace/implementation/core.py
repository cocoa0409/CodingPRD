"""Core infrastructure: in-memory store, logical clock, errors, envelopes, auth."""
import random
import re
import string
import threading
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import g, request, jsonify

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # existence
    "ERR_CERTIFICATION_STANDARD_NOT_FOUND": 404,
    "ERR_ACADEMY_CLASS_NOT_FOUND": 404,
    "ERR_RECRUIT_NOT_FOUND": 404,
    "ERR_SCREENING_RECORD_NOT_FOUND": 404,
    "ERR_INSTRUCTOR_NOT_FOUND": 404,
    "ERR_LESSON_PLAN_NOT_FOUND": 404,
    "ERR_COURSE_SESSION_NOT_FOUND": 404,
    "ERR_ATTENDANCE_RECORD_NOT_FOUND": 404,
    "ERR_EXAMINATION_NOT_FOUND": 404,
    "ERR_ROTATION_NOT_FOUND": 404,
    "ERR_OBSERVATION_REPORT_NOT_FOUND": 404,
    "ERR_TRAINING_RECORD_ENTRY_NOT_FOUND": 404,
    # shape / syntax
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_INTERVAL": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_CLOCK_NOT_MONOTONIC": 400,
    # uniqueness
    "ERR_DUPLICATE_IDENTIFIER": 409,
    # optimistic concurrency
    "ERR_STALE_RECRUIT_VERSION": 412,
    "ERR_STALE_LESSON_PLAN_VERSION": 412,
    # state family
    "ERR_INVALID_STATE": 409,
    "ERR_SCREENING_ALREADY_ADJUDICATED": 409,
    "ERR_SESSION_NOT_DELIVERABLE": 409,
    "ERR_SESSION_NOT_VOIDABLE": 409,
    "ERR_ROTATION_NOT_ACTIVE": 409,
    "ERR_PROBATION_NOT_ACTIVE": 409,
    "ERR_STAGE_TRANSITION_NOT_ALLOWED": 409,
    "ERR_RECRUIT_TERMINAL": 409,
    "ERR_RECRUIT_NOT_IN_ACADEMY": 409,
    # eligibility / business rules
    "ERR_INSTRUCTOR_NOT_AUTHORIZED": 422,
    "ERR_INSTRUCTOR_CERT_EXPIRED": 422,
    "ERR_LESSON_PLAN_NOT_APPROVED": 422,
    "ERR_CLEARANCE_INCOMPLETE": 422,
    "ERR_DISQUALIFIER_UNWAIVED": 422,
    "ERR_FITNESS_STANDARD_NOT_MET": 422,
    "ERR_SAME_ACTOR_ADJUDICATION": 422,
    "ERR_FTO_NOT_CERTIFIED": 422,
    "ERR_ROTATION_DATE_OVERLAP": 409,
    "ERR_DOR_OUTSIDE_ROTATION_WINDOW": 422,
    "ERR_INSTRUCTOR_SCHEDULE_CONFLICT": 409,
    "ERR_TRAINER_ROTATION_VIOLATION": 409,
    "ERR_DOR_AUTHOR_NOT_ASSIGNED_FTO": 422,
    "ERR_DUPLICATE_DOR": 409,
    "ERR_ATTENDANCE_ALREADY_RECORDED": 409,
    "ERR_DUPLICATE_SCREENING_TYPE": 409,
    "ERR_PRESENT_HOURS_INCONSISTENT": 422,
    "ERR_TOPIC_NOT_IN_STANDARD": 422,
    "ERR_EXAM_NOT_REQUIRED_FOR_TOPIC": 422,
    "ERR_PRIOR_ROTATION_MISMATCH": 422,
    "ERR_FTO_LOAD_EXCEEDED": 409,
    "ERR_REMEDIATION_ATTEMPTS_EXHAUSTED": 409,
    "ERR_MILESTONE_NOT_REACHED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = status if status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?([Zz]|[+-]\d{2}:\d{2})$"
)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO-8601 UTC instant; return an aware datetime truncated to seconds."""
    if not isinstance(value, str):
        return None
    m = INSTANT_RE.match(value.strip())
    if not m:
        return None
    text = value.strip()
    frac = m.group(7)
    if frac:
        text = text.replace(frac, "")
    tz = m.group(8)
    if tz in ("Z", "z"):
        text = text[: -len(tz)] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_instant(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_instant_ms(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")
ZERO2 = Decimal("0.00")


def d2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def d4(value):
    return Decimal(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal/int for JSON output."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------------------
# In-memory store (no seeding: every collection starts empty)
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "standards",
    "classes",
    "recruits",
    "screenings",
    "instructors",
    "plans",
    "sessions",
    "attendance",
    "exams",
    "rotations",
    "reports",
    "entries",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now():
    return store.clock


def today():
    return store.clock.date()


def new_id():
    return "".join(random.choice(string.hexdigits.lower()[:16]) for _ in range(8)) + "-" + \
        "".join(random.choice(string.hexdigits.lower()[:16]) for _ in range(4)) + "-" + \
        "".join(random.choice(string.hexdigits.lower()[:16]) for _ in range(4)) + "-" + \
        "".join(random.choice(string.hexdigits.lower()[:4]) for _ in range(4)) + "-" + \
        "".join(random.choice(string.hexdigits.lower()[:16]) for _ in range(12))


def base_row():
    stamp = fmt_instant_ms(now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(row):
    """Bump updated_at/version at most once per row per request."""
    if row is None:
        return
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = id(row)
    if key in touched:
        return
    touched.add(key)
    row["updated_at"] = fmt_instant_ms(now())
    row["version"] = int(row.get("version", 1)) + 1


def ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------

ALNUM = string.ascii_letters + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_instant_ms(now()),
    }


def respond(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Authentication / roles  (ladder rungs 1-4)
# ---------------------------------------------------------------------------

ROLES = (
    "AcademyDirector",
    "TrainingCoordinator",
    "BackgroundInvestigator",
    "MedicalExaminer",
    "AcademyInstructor",
    "FieldTrainingOfficer",
    "RecordsCustodian",
    "Recruit",
)


def authenticate():
    """Rung 1 and rung 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "unrecognised role: %s" % role)
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, role


def require_roles(*allowed):
    """Rung 3."""
    if g.role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not perform this operation" % g.role)


def not_owner():
    fail("ERR_NOT_RESOURCE_OWNER", "acting identity does not own this resource")


# ---------------------------------------------------------------------------
# Pagination (rung 22)
# ---------------------------------------------------------------------------

INT_RE = re.compile(r"^[+-]?\d+$")


def _query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not INT_RE.match(raw):
        fail("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    return int(raw)


def pagination():
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = 10
    elif limit < 1 or limit > 100:
        fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    elif offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset must be zero or greater")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset: offset + limit], total
