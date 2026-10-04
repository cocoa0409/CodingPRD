"""Foundation: logical clock, in-memory store, errors, envelope, auth, schema helpers."""
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalogue (PRD S5) -- error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_FORBIDDEN_SCOPE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_OUTSIDE_COVERAGE_WINDOW": 422,
    "ERR_CONTRACT_WINDOW_OVERLAP": 409,
    "ERR_COMPONENT_SUM_MISMATCH": 409,
    "ERR_IMPLANT_CAP_EXCEEDED": 409,
    "ERR_PRIORITY_BLOCKED": 409,
    "ERR_DUPLICATE_CASE_CLAIM": 409,
    "ERR_DUPLICATE_INTAKE_REQUEST": 409,
    "ERR_ACTIVE_EPISODE_EXISTS": 409,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_BENEFIT_POOL_EXCEEDED": 422,
    "ERR_REQUIRED_CARE_INCOMPLETE": 422,
    "ERR_PENDING_CLAIMS": 422,
    "ERR_PATIENT_EMPLOYER_MISMATCH": 422,
    "ERR_TEMPLATE_RETIRED": 422,
    "ERR_EMPLOYER_TERMINATED": 422,
    "ERR_CLAIM_OUTSIDE_WARRANTY": 422,
    "ERR_READMISSION_POLICY_SCOPE": 422,
    "ERR_CLAIM_BEFORE_SURGERY": 422,
    "ERR_BENEFIT_KIND_MISMATCH": 422,
    "ERR_MONTH_FORMAT_INVALID": 400,
    "ERR_EPISODE_NOT_APPROVED": 422,
    "ERR_NO_IN_WINDOW_READMISSION": 422,
    "ERR_VIEW_UNKNOWN": 400,
    "ERR_RATE_FAMILY_MISSING": 422,
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
# Roles (PRD S2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "ProgramAdmin",
    "EmployerRep",
    "CareCoordinator",
    "PhysicianReviewer",
    "ClaimsAdmin",
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


_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# ---------------------------------------------------------------------------
# In-memory store -- starts EMPTY on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    COLLECTIONS = (
        "employers",
        "templates",
        "rate_books",
        "contracts",
        "patients",
        "episodes",
        "screenings",
        "reviews",
        "claims",
        "readmissions",
        "benefits",
        "care_items",
        "reports",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.amendment_day = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_amendment_day(self):
        """Contract-local amendment day counter (PRD 3.2): `effective_from_seq`
        is a day stamp on the same axis as the episodes' per-episode
        `screen_seq` day counters, so the 30-day prior-notice gap of 3.4
        measures episode activity days elapsed since the amendment."""
        self.amendment_day += 1
        return self.amendment_day


db = Store()


def now():
    return db.clock


def new_row(entity_kind, audited=True, **fields):
    row = {
        "_kind": entity_kind,
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
# Response envelope (PRD S2.2)
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
        jsonify({"meta": _meta(), "response_type": "object", "data": jsonable(data)}),
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
# Auth (priority tiers 1 and 2)
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
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def scope_employer(employer_id):
    """Priority tier 3: EmployerRep may only act on their own employer chain."""
    if g.role == "EmployerRep" and g.user_id != employer_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE")


# ---------------------------------------------------------------------------
# Body validation helpers (priority tier 5)
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


def f_dt(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        bad_request("Field '%s' must be an ISO-8601 UTC timestamp." % key)
    return parsed


def f_map(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, dict):
        bad_request("Field '%s' must be an object." % key)
    return dict(value)


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
