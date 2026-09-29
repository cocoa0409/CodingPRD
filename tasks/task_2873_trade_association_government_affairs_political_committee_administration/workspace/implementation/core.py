"""Errors, logical clock, in-memory store, response envelope and auth (PRD 2.1-2.4)."""
import datetime
import random
import re
import string
import uuid

from flask import g, jsonify, request

from constants import ROLES

# --------------------------------------------------------------------------- #
# Error catalogue (PRD section 5)
# --------------------------------------------------------------------------- #
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_MEMBER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_COMMITTEE_NOT_FOUND": 404,
    "ERR_POSITION_NOT_FOUND": 404,
    "ERR_VOTE_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_ACTIVITY_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_PRIOR_APPROVAL_NOT_FOUND": 404,
    "ERR_CANDIDATE_NOT_FOUND": 404,
    "ERR_FUND_NOT_FOUND": 404,
    "ERR_CONTRIBUTION_NOT_FOUND": 404,
    "ERR_INVALID_POSITION_STATE": 409,
    "ERR_INVALID_REGISTRATION_STATE": 409,
    "ERR_INVALID_REPORT_STATE": 409,
    "ERR_INVALID_CAMPAIGN_STATE": 409,
    "ERR_INVALID_PRIOR_APPROVAL_STATE": 409,
    "ERR_DISSENT_NOT_FILED": 409,
    "ERR_ACTIVITY_ALREADY_VOIDED": 409,
    "ERR_CONTRIBUTION_NOT_PENDING": 409,
    "ERR_CONTRIBUTION_NOT_APPROVED": 409,
    "ERR_CONTRIBUTION_SUSPENDED": 409,
    "ERR_COMMITTEE_FORMING": 409,
    "ERR_COMMITTEE_NOT_QUORATE": 409,
    "ERR_REGISTRATION_NOT_ACTIVE": 409,
    "ERR_PRIOR_APPROVAL_NOT_GRANTED": 409,
    "ERR_PRIOR_APPROVAL_EXPIRED": 409,
    "ERR_FUND_RESTRICTED": 409,
    "ERR_POSITION_NOT_ADOPTED": 409,
    "ERR_MEMBER_NOT_SEATED": 409,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_COALITION_PARTNER_REQUIRED": 422,
    "ERR_JURISDICTION_SCOPE_MISMATCH": 422,
    "ERR_PRIOR_APPROVAL_WINDOW_CONFLICT": 409,
    "ERR_PRIOR_APPROVAL_WINDOW_INVALID": 422,
    "ERR_REGISTRATION_COVERAGE_OVERLAP": 409,
    "ERR_ALERT_COOLING_PERIOD": 409,
    "ERR_ACTIVITY_OUTSIDE_COVERAGE": 422,
    "ERR_PERIOD_CADENCE_MISMATCH": 422,
    "ERR_PERIOD_NOT_CLOSED": 409,
    "ERR_DUPLICATE_SEAT": 409,
    "ERR_CHAIR_SEAT_TAKEN": 409,
    "ERR_MAX_BALLOT_ROUNDS": 409,
    "ERR_NO_BALLOTS_CAST": 409,
    "ERR_DISSENT_REQUIRES_OPPOSE": 409,
    "ERR_EMPTY_ACTIVITY": 422,
    "ERR_EMPTY_REPORT": 422,
    "ERR_OPEN_REPORT_BLOCKS_TERMINATION": 422,
    "ERR_ACTIVITY_IN_CERTIFIED_REPORT": 422,
    "ERR_CLASS_SIZE_EXCEEDED": 422,
    "ERR_SCORE_BELOW_FLOOR": 422,
    "ERR_CONTRIBUTION_LIMIT_EXCEEDED": 422,
    "ERR_INSUFFICIENT_FUND_BALANCE": 422,
    "ERR_STALE_REGISTRATION_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    body = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % body


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------- #
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------- #
DEFAULT_CLOCK = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_CLOCK = {"now": DEFAULT_CLOCK}

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def now_dt():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def reset_clock():
    _CLOCK["now"] = DEFAULT_CLOCK


def format_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(datetime.timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    offset = datetime.timezone.utc
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        offset = datetime.timezone(sign * datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))
    try:
        dt = datetime.datetime(year, month, day, hour, minute, second, micro, tzinfo=offset)
    except ValueError:
        return None
    return dt.astimezone(datetime.timezone.utc)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    """Strict ISO YYYY-MM-DD calendar date -> datetime.date, else None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def clock_date():
    return now_dt().astimezone(datetime.timezone.utc).date()


def instant_date(iso_instant):
    dt = parse_instant(iso_instant)
    return dt.date() if dt else None


def iso_date(d):
    return d.isoformat() if d is not None else None


# --------------------------------------------------------------------------- #
# In-memory store.  Starts empty on every boot; nothing is ever seeded.
# --------------------------------------------------------------------------- #
COLLECTIONS = (
    "members",
    "committees",
    "seats",
    "positions",
    "votes",
    "registrations",
    "activities",
    "reports",
    "campaigns",
    "alerts",
    "approvals",
    "candidates",
    "funds",
    "contributions",
)

STORE = {name: {} for name in COLLECTIONS}
_SEQ = {"n": 0}


def coll(name):
    return STORE[name]


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields, common=True):
    """Persist a new row.  `common` controls created_at/updated_at/version."""
    row = {"id": new_id()}
    row.update(fields)
    stamp = format_instant(now_dt())
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    STORE[collection][row["id"]] = row
    return row


def touch(row):
    """Register a mutation: refresh updated_at and increment version (PRD 2.4)."""
    if row is None or "version" not in row:
        return row
    row["updated_at"] = format_instant(now_dt())
    row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """created_at ascending; insertion sequence breaks equal logical-clock stamps."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def rows_of(collection):
    return list(STORE[collection].values())


# --------------------------------------------------------------------------- #
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------- #
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    real = datetime.datetime.now(datetime.timezone.utc)
    return {"api_request_id": _request_id(), "api_request_timestamp": format_instant(real)}


def respond(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def respond_list(items, pagination, status=200):
    return respond(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------- #
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------- #
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _int_arg(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if value < minimum or (maximum is not None and value > maximum):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def paginate(rows):
    limit = _int_arg("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _int_arg("offset", DEFAULT_OFFSET, 0, None)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def int_arg(name):
    raw = arg(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


# --------------------------------------------------------------------------- #
# Authentication / RBAC (PRD 2.1, precedence ranks 1-3)
# --------------------------------------------------------------------------- #
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    user_id = user_id.strip() if isinstance(user_id, str) else ""
    role = role.strip() if isinstance(role, str) else ""
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not access this endpoint." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def body():
    """Request JSON body as a dict (absent body is treated as empty)."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def member_scope(member_id):
    """Precedence rank 5: a MemberDelegate acts only within its own member scope."""
    if g.get("role") == "MemberDelegate" and g.get("user_id") != member_id:
        fail("ERR_MEMBER_SCOPE_VIOLATION", "A MemberDelegate may only act on its own member scope.")


def filtered(rows, **criteria):
    """Apply list filters (PRD 2.3): filters run before pagination."""
    out = rows
    for field, value in criteria.items():
        if value is None:
            continue
        out = [r for r in out if r.get(field) == value]
    return out
