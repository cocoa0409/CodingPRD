"""Foundation: logical clock, in-memory store, errors, envelope, auth, schema helpers."""
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalogue (§5) -- error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    # auth / ownership
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_ASSIGNED_INVESTIGATOR": 403,
    "ERR_NOT_PLAN_SUPERVISOR": 403,
    "ERR_INTAKE_CODE_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not found
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_OFFICER_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_ALLEGATION_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_DISCIPLINE_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_REINSTATEMENT_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_CHECKIN_NOT_FOUND": 404,
    "ERR_DISCLOSURE_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 400,
    # concurrency
    "ERR_STALE_INVESTIGATION_VERSION": 412,
    "ERR_STALE_ALERT_VERSION": 412,
    # state
    "ERR_COMPLAINT_STATE_INVALID": 409,
    "ERR_COMPLAINT_NOT_PURGEABLE": 409,
    "ERR_INVESTIGATION_STATE_INVALID": 409,
    "ERR_INVESTIGATION_NOT_INTERVIEWABLE": 409,
    "ERR_OFFICER_SEPARATED": 409,
    "ERR_SESSION_STATE_INVALID": 409,
    "ERR_ALLEGATION_ALREADY_DISPOSED": 409,
    "ERR_DISCIPLINE_STATE_INVALID": 409,
    "ERR_APPEAL_STATE_INVALID": 409,
    "ERR_REINSTATEMENT_ALREADY_FINALIZED": 409,
    "ERR_ALERT_STATE_INVALID": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_CHECKIN_NOT_PENDING": 409,
    "ERR_DISCLOSURE_NOT_ACTIVE": 409,
    # business safety
    "ERR_INVESTIGATOR_CONFLICT": 422,
    "ERR_INSUFFICIENT_NOTICE": 422,
    "ERR_REPRESENTATION_NOT_PRESENT": 409,
    "ERR_CREDIBILITY_HOLD": 409,
    "ERR_APPEAL_PENDING": 409,
    # business referential
    "ERR_NO_ALLEGATIONS": 422,
    "ERR_INVESTIGATION_ALREADY_EXISTS": 409,
    "ERR_FINDINGS_INCOMPLETE": 422,
    "ERR_NO_INTERVIEW_HELD": 422,
    "ERR_PENDING_DISPOSITIONS": 409,
    "ERR_NO_INTAKE_UNIT": 422,
    "ERR_NO_ELIGIBLE_INVESTIGATOR": 422,
    "ERR_ALERT_ALREADY_OPEN": 409,
    "ERR_PENDING_CHECKINS": 409,
    "ERR_PLAN_EXISTS": 409,
    # business temporal
    "ERR_STATUTE_EXPIRED": 422,
    "ERR_EVENT_IN_FUTURE": 422,
    "ERR_INVALID_SESSION_WINDOW": 422,
    "ERR_OFFICER_REST_BUFFER_CONFLICT": 409,
    "ERR_ROOM_CAPACITY_EXCEEDED": 409,
    "ERR_INTERVIEW_NOT_STARTED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_RETENTION_NOT_EXPIRED": 409,
    "ERR_INVALID_REPORT_PERIOD": 422,
    # business constraint
    "ERR_PREPONDERANCE_NOT_MET": 422,
    "ERR_DISPOSITION_NOT_SUPPORTED": 422,
    "ERR_MAX_POSTPONEMENTS_REACHED": 409,
    "ERR_MAX_RECLASSIFICATIONS_REACHED": 409,
    "ERR_COMPLAINANT_IDENTITY_REQUIRED": 422,
    "ERR_ANONYMOUS_NOT_WITHDRAWABLE": 422,
    "ERR_SUSTAINED_NOT_WITHDRAWABLE": 409,
    "ERR_BADGE_NUMBER_DUPLICATE": 409,
    "ERR_CASE_LOAD_EXCEEDED": 422,
    "ERR_CERTIFICATION_INSUFFICIENT": 422,
    "ERR_MODIFIED_DAYS_INVALID": 422,
    # business fiscal
    "ERR_INVALID_INTERIM_EARNINGS": 422,
    "ERR_SALARY_UNKNOWN": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words.capitalize() + "."


# ---------------------------------------------------------------------------
# Roles (§1.7)
# ---------------------------------------------------------------------------
ROLES = (
    "Complainant",
    "Supervisor",
    "Investigator",
    "IACommander",
    "AppealsOfficer",
    "OfficerRepresentative",
    "RecordsCustodian",
    "SystemAdmin",
)

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"


# ---------------------------------------------------------------------------
# Decimal / time helpers
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    """round_half_up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def floor_div_seconds(delta, seconds):
    return int(delta.total_seconds() // seconds)


def floor_days(later, earlier):
    return floor_div_seconds(later - earlier, 86400)


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(text):
    """Parse an ISO-8601 datetime; returns None when unparseable."""
    if not isinstance(text, str):
        return None
    m = _DT_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1_000_000))
    tzpart = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body = tzpart[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


# ---------------------------------------------------------------------------
# In-memory store -- starts EMPTY on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    COLLECTIONS = (
        "units",
        "officers",
        "rooms",
        "complaints",
        "allegations",
        "investigations",
        "sessions",
        "disciplines",
        "appeals",
        "reinstatements",
        "events",
        "alerts",
        "plans",
        "checkins",
        "disclosures",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.intake_sequence = 0
        self.run_sequence = 0
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def new_row(kind, audited=True, **fields):
    row = {
        "_kind": kind,
        "_seq": db.next_seq(),
        "id": str(uuid.uuid4()),
        "created_at": db.clock,
    }
    if audited:
        row["updated_at"] = db.clock
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump the audit fields. Cascades call this too."""
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = db.clock
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dump(row, extra=None):
    if row is None:
        return None
    out = {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}
    if extra:
        out.update({k: jsonable(v) for k, v in extra.items()})
    return out


# ---------------------------------------------------------------------------
# Response envelope (§2.2)
# ---------------------------------------------------------------------------
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _meta():
    token = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    return {
        "api_request_id": "req_" + token,
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }


def respond_object(data, status=200):
    return (
        jsonify(
            {"meta": _meta(), "response_type": "object", "data": jsonable(data)}
        ),
        status,
    )


def respond_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return (
        jsonify({"meta": meta, "response_type": "array", "data": jsonable(items)}),
        status,
    )


def respond_error(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# Auth (tiers 1 and 2)
# ---------------------------------------------------------------------------
def endpoint(*roles):
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(HDR_USER)
            role = request.headers.get(HDR_ROLE)
            if not (user_id or "").strip() or not (role or "").strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ROLES or role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Tier 4 -- schema validation helpers
# ---------------------------------------------------------------------------
_MISSING = object()


def bad_request(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


def body():
    """Parse the JSON body. An absent body behaves as an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


def _fetch(src, key, required):
    if key not in src or src[key] is None:
        if required:
            bad_request("Field '%s' is required." % key)
        return _MISSING
    return src[key]


def f_str(src, key, required=True, allow_empty=False):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad_request("Field '%s' must not be empty." % key)
    return value


def f_enum(src, key, domain, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in domain:
        bad_request("Field '%s' must be one of %s." % (key, ", ".join(domain)))
    return value


def f_bool(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def f_int(src, key, required=True, default=None, minimum=None, maximum=None, choices=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be at most %s." % (key, maximum))
    if choices is not None and value not in choices:
        bad_request("Field '%s' must be one of %s." % (key, choices))
    return value


def f_num(src, key, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad_request("Field '%s' must be a number." % key)
    dec = D(value)
    if minimum is not None and dec < D(minimum):
        bad_request("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and dec > D(maximum):
        bad_request("Field '%s' must be at most %s." % (key, maximum))
    return dec


def f_dt(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        bad_request("Field '%s' must be an ISO-8601 UTC timestamp." % key)
    return parsed


def f_enum_list(src, key, domain, required=True, default=None, non_empty=True):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % key)
    if non_empty and len(value) == 0:
        bad_request("Field '%s' must not be empty." % key)
    for member in value:
        if not isinstance(member, str) or member not in domain:
            bad_request("Field '%s' members must be one of %s." % (key, ", ".join(domain)))
    return list(value)


# ---------------------------------------------------------------------------
# Query-string helpers
# ---------------------------------------------------------------------------
def q_str(key, default=None):
    if key not in request.args:
        return default
    value = request.args.get(key)
    if value is None or value == "":
        return default
    return value


def q_enum(key, domain, default=None):
    value = q_str(key)
    if value is None:
        return default
    if value not in domain:
        bad_request("Query parameter '%s' must be one of %s." % (key, ", ".join(domain)))
    return value


def q_bool(key, default=None):
    value = q_str(key)
    if value is None:
        return default
    low = value.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    bad_request("Query parameter '%s' must be true or false." % key)


def q_int(key, default=None, minimum=None, maximum=None):
    value = q_str(key)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        bad_request("Query parameter '%s' must be an integer." % key)
    if minimum is not None and parsed < minimum:
        bad_request("Query parameter '%s' must be at least %s." % (key, minimum))
    if maximum is not None and parsed > maximum:
        bad_request("Query parameter '%s' must be at most %s." % (key, maximum))
    return parsed


def q_dt(key, required=False, default=None):
    value = q_str(key)
    if value is None:
        if required:
            bad_request("Query parameter '%s' is required." % key)
        return default
    parsed = parse_dt(value)
    if parsed is None:
        bad_request("Query parameter '%s' must be an ISO-8601 UTC timestamp." % key)
    return parsed


PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def pagination():
    limit = q_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = q_int("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, dumper=None):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    dumper = dumper or dump
    return respond_list([dumper(r) for r in page], total, limit, offset)
