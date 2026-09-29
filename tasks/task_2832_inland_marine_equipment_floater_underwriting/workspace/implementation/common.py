"""Shared primitives: logical clock, response envelope, errors, parsing helpers."""
import datetime
import random
import re
import string
import uuid
from fractions import Fraction

from flask import g, jsonify, request

API_PREFIX = "/inland-marine"

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLES = ("Actuary", "Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")

# --------------------------------------------------------------------------
# Error catalogue: error_id -> HTTP status
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_POLICY_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_COVERAGE_PART_NOT_FOUND": 404,
    "ERR_RATE_RULE_NOT_FOUND": 404,
    "ERR_EQUIPMENT_ITEM_NOT_FOUND": 404,
    "ERR_JOBSITE_NOT_FOUND": 404,
    "ERR_INSTALLATION_FLOATER_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_TRANSIT_SHIPMENT_NOT_FOUND": 404,
    "ERR_VALUE_REPORT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_LOSS_SUBJECT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_POLICY_NOT_QUOTABLE": 409,
    "ERR_POLICY_NOT_REFERRABLE": 409,
    "ERR_REFERRAL_NOT_PENDING": 409,
    "ERR_POLICY_NOT_BINDABLE": 409,
    "ERR_POLICY_NOT_ACTIVATABLE": 409,
    "ERR_POLICY_ALREADY_TERMINAL": 409,
    "ERR_POLICY_NOT_MUTABLE": 409,
    "ERR_POLICY_NOT_IN_FORCE": 409,
    "ERR_PART_VOID": 409,
    "ERR_RATE_RULE_NOT_DRAFT": 409,
    "ERR_ITEM_ALREADY_OFF_RISK": 409,
    "ERR_FLOATER_NOT_IN_REQUIRED_STATE": 409,
    "ERR_VEHICLE_ALREADY_APPROVED": 409,
    "ERR_VEHICLE_NOT_APPROVED": 409,
    "ERR_SHIPMENT_NOT_IN_REQUIRED_STATE": 409,
    "ERR_REPORT_ALREADY_ADJUDICATED": 409,
    "ERR_CLAIM_NOT_IN_REQUIRED_STATE": 409,
    "ERR_CLAIM_NOT_SETTLED": 409,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_STALE_COVERAGE_PART_VERSION": 412,
    "ERR_JOBSITE_SECURITY_INSUFFICIENT": 422,
    "ERR_GEO_TRACKING_REQUIRED": 422,
    "ERR_VEHICLE_APPROVAL_EXPIRED": 422,
    "ERR_CARRIER_APPROVAL_MISSING": 422,
    "ERR_FLOATER_OUTSIDE_POLICY_TERM": 422,
    "ERR_TERMINATION_DATE_OUTSIDE_COVERAGE": 422,
    "ERR_LOSS_DATE_OUTSIDE_TERM": 422,
    "ERR_REPORT_PERIOD_OUTSIDE_TERM": 422,
    "ERR_REPORT_PERIOD_MISALIGNED": 422,
    "ERR_CANCEL_DATE_OUTSIDE_TERM": 422,
    "ERR_PART_TYPE_MISMATCH": 422,
    "ERR_LOSS_SUBJECT_NOT_ON_PART": 422,
    "ERR_LOSS_OF_USE_NOT_COVERED": 422,
    "ERR_NO_PUBLISHED_RATE_RULE": 422,
    "ERR_JOBSITE_FLOATER_OVERLAP": 409,
    "ERR_VEHICLE_WINDOW_CONFLICT": 409,
    "ERR_VEHICLE_CAPACITY_EXCEEDED": 422,
    "ERR_NO_RATABLE_COVERAGE": 422,
    "ERR_CONSTRUCTIVE_TOTAL_LOSS": 409,
    "ERR_REPORTING_DELINQUENT": 409,
    "ERR_REFERRAL_REQUIRED": 422,
    "ERR_ITEM_VALUE_EXCEEDS_PER_ITEM_LIMIT": 422,
    "ERR_FLOATER_LIMIT_EXCEEDS_PART_AGGREGATE": 422,
    "ERR_TRANSIT_VALUE_EXCEEDS_LIMIT": 422,
    "ERR_REPORTED_VALUE_EXCEEDS_LIMIT": 422,
    "ERR_AGGREGATE_LIMIT_EXHAUSTED": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
CLOCK_EPOCH = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


def clock_date():
    return _clock["now"].date()


def clock_year():
    return _clock["now"].year


def fmt_instant(dt):
    dt = dt.astimezone(datetime.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(clock_now())


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# --------------------------------------------------------------------------
# Arithmetic
# --------------------------------------------------------------------------
def rhu(value):
    """Round a Fraction/int half-up to the nearest integer."""
    frac = value if isinstance(value, Fraction) else Fraction(value)
    n, d = frac.numerator, frac.denominator
    if d == 1:
        return n
    return (2 * n + d) // (2 * d)


def F(*args):
    return Fraction(*args)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
_ALNUM = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(16))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def envelope_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def envelope_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def envelope_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# Authentication / authorisation (ladder rungs 1-3)
# --------------------------------------------------------------------------
def require(*allowed_roles):
    """Rung 1: both headers present and non-blank.  Rung 2: role recognised.
    Rung 3: role appears in the endpoint's authorised list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or blank")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or blank")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised role '%s'" % role)
    if allowed_roles and role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not perform this operation" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def own_policy(policy_id):
    """Rung 4: a Policyholder caller must present the owning policy's id.
    Called only for the seven ownership-guarded operations.  ``policy_id`` may
    be None when the owning policy is not resolvable yet, in which case the
    check is vacuous and the later existence rung reports the 404."""
    if getattr(g, "role", None) != "Policyholder":
        return
    if policy_id is None:
        return
    if str(g.user_id) != str(policy_id):
        fail("ERR_NOT_POLICY_OWNER", "Caller does not own policy %s" % policy_id)


# --------------------------------------------------------------------------
# Pagination (rung 10)
# --------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    raw = args.get("limit")
    if raw is not None:
        if not re.fullmatch(r"[+-]?\d+", raw.strip()):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    raw = args.get("offset")
    if raw is not None:
        if not re.fullmatch(r"[+-]?\d+", raw.strip()):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        offset = int(raw.strip())
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must not be negative")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# --------------------------------------------------------------------------
# Body / shape helpers (rung 9)
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return payload


def bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def get_str(b, field, required=True, min_len=1, max_len=None, default=None):
    if field not in b or b[field] is None:
        if required:
            bad(field, "is required")
        return default
    val = b[field]
    if not isinstance(val, str):
        bad(field, "must be a string")
    if len(val) < min_len:
        bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(val) > max_len:
        bad(field, "must be at most %d characters" % max_len)
    return val


def get_enum(b, field, allowed, required=True, default=None):
    if field not in b or b[field] is None:
        if required:
            bad(field, "is required")
        return default
    val = b[field]
    if not isinstance(val, str) or val not in allowed:
        bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return val


def get_int(b, field, required=True, minimum=None, maximum=None, default=None):
    if field not in b or b[field] is None:
        if required:
            bad(field, "is required")
        return default
    val = b[field]
    if isinstance(val, bool) or not isinstance(val, int):
        bad(field, "must be an integer")
    if minimum is not None and val < minimum:
        bad(field, "must be >= %d" % minimum)
    if maximum is not None and val > maximum:
        bad(field, "must be <= %d" % maximum)
    return val


def get_bool(b, field, required=True, default=None):
    if field not in b or b[field] is None:
        if required:
            bad(field, "is required")
        return default
    val = b[field]
    if not isinstance(val, bool):
        bad(field, "must be a boolean")
    return val


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def get_date(b, field, required=True, default=None):
    if field not in b or b[field] is None:
        if required:
            bad(field, "is required")
        return default
    val = b[field]
    if not isinstance(val, str) or not _DATE_RE.match(val):
        bad(field, "must be an ISO 8601 date (YYYY-MM-DD)")
    y, m, d = (int(p) for p in val.split("-"))
    try:
        return datetime.date(y, m, d)
    except ValueError:
        bad(field, "is not a valid calendar date")


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_instant_str(val, field="value"):
    if not isinstance(val, str):
        bad(field, "must be an ISO 8601 instant string")
    m = _INSTANT_RE.match(val.strip())
    if not m:
        bad(field, "must be an ISO 8601 UTC instant")
    y, mo, d, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime.datetime(y, mo, d, hh, mm, ss, micro, tzinfo=datetime.timezone.utc)
    except ValueError:
        bad(field, "is not a valid instant")
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body_tz = tz[1:].replace(":", "")
        offset = datetime.timedelta(hours=int(body_tz[:2]), minutes=int(body_tz[2:4]))
        dt = dt - sign * offset
    return dt


def get_instant(b, field, required=True, default=None):
    if field not in b or b[field] is None:
        if required:
            bad(field, "is required")
        return default
    return parse_instant_str(b[field], field)


def new_id():
    return str(uuid.uuid4())
