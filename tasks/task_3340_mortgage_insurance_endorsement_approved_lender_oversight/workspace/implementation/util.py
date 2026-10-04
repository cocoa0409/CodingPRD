"""Response envelope, error catalog, date math, and rounding helpers."""
import random
import string
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from store import stamp_now

# ---------------------------------------------------------------------------
# Error catalog (id -> HTTP status), from SCAFFOLD §1.6 / PRD §5.
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CASE_BLOCKED": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_REVIEWER_CONFLICT": 422,
    "ERR_LENDER_NOT_APPROVED": 409,
    "ERR_APPRAISAL_NOT_ACCEPTED": 409,
    "ERR_REVIEW_ALREADY_OPEN": 409,
    "ERR_CASE_ALREADY_HAS_APPRAISAL": 409,
    "ERR_INDEMNIFICATION_BLOCKS_PAYMENT": 409,
    "ERR_DEFECTS_OPEN": 409,
    "ERR_LENDER_HAS_ACTIVE_CASES": 409,
    "ERR_APPRAISAL_EXPIRED": 409,
    "ERR_TRANSFER_WINDOW_CLOSED": 409,
    "ERR_FILING_STALE": 422,
    "ERR_REVIEW_WINDOW_PASSED": 422,
    "ERR_CLAIM_DEADLINE_PASSED": 422,
    "ERR_ESCROW_EXPIRED": 409,
    "ERR_ESCROW_WINDOW_OVERLAP": 409,
    "ERR_ESCROW_FROZEN": 409,
    "ERR_WATERFALL_ORDER_VIOLATION": 409,
    "ERR_WATERFALL_NOT_EXHAUSTED": 409,
    "ERR_MODIFICATION_INSUFFICIENT_REDUCTION": 422,
    "ERR_VINTAGE_LIFE_OF_LOAN": 422,
    "ERR_MIP_CANCELLATION_INELIGIBLE": 422,
    "ERR_NET_WORTH_DEFICIENT": 422,
    "ERR_LIQUIDITY_DEFICIENT": 422,
    "ERR_QC_PLAN_MISSING": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERROR_HTTP[error_id]


def verr(message):
    raise ApiError("ERR_VALIDATION", message)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope / PRD §2.2).
# ---------------------------------------------------------------------------
def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": stamp_now()}


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Results sorted by created_at ascending (creation sequence as tiebreak).
# ---------------------------------------------------------------------------
def paginate(entities):
    entities = sorted(entities, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(entities)
    page = entities[offset:offset + limit]
    return ok_list([{k: v for k, v in e.items() if not k.startswith("_")} for e in page],
                   limit, offset, total)


# ---------------------------------------------------------------------------
# Request body helpers.
# ---------------------------------------------------------------------------
MISSING = object()


def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def need_int(b, name, minimum=None):
    v = b.get(name, MISSING)
    if v is MISSING:
        verr("missing required field: %s" % name)
    if not is_int(v):
        verr("field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        verr("field %s must be >= %d" % (name, minimum))
    return v


def need_str(b, name, nonempty=True):
    v = b.get(name, MISSING)
    if v is MISSING:
        verr("missing required field: %s" % name)
    if not isinstance(v, str) or (nonempty and not v.strip()):
        verr("field %s must be a non-empty string" % name)
    return v


def need_enum(b, name, values):
    v = b.get(name, MISSING)
    if v is MISSING:
        verr("missing required field: %s" % name)
    if v not in values:
        verr("field %s must be one of %s" % (name, ", ".join(values)))
    return v


# ---------------------------------------------------------------------------
# Date / datetime helpers.
# ---------------------------------------------------------------------------
def parse_date(s):
    """Strict ISO date YYYY-MM-DD -> datetime.date; raises ValueError."""
    if not isinstance(s, str) or len(s) != 10:
        raise ValueError("not an ISO date")
    d = datetime.strptime(s, "%Y-%m-%d").date()
    if d.isoformat() != s:
        raise ValueError("not an ISO date")
    return d


def parse_dt(s):
    """ISO 8601 datetime -> aware UTC datetime; raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not an ISO datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _days_in_month(y, m):
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return (nxt - date(y, m, 1)).days


def add_months_date(d, n):
    total = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(total, 12)
    m = m0 + 1
    day = min(d.day, _days_in_month(y, m))
    return date(y, m, day)


def add_months_dt(dt, n):
    d = add_months_date(dt.date(), n)
    return dt.replace(year=d.year, month=d.month, day=d.day)


def months_between(d1, d2):
    """Complete calendar months between d1 and d2 (dates or datetimes)."""
    m = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        m -= 1
    elif d2.day == d1.day and isinstance(d1, datetime) and isinstance(d2, datetime):
        if (d2.hour, d2.minute, d2.second, d2.microsecond) < \
           (d1.hour, d1.minute, d1.second, d1.microsecond):
            m -= 1
    return m


def days_later(d, n):
    return d + timedelta(days=n)


# ---------------------------------------------------------------------------
# Rounding: integer cents / basis points, round half-up (ties away from zero).
# ---------------------------------------------------------------------------
def rhu(numer, denom):
    """round_half_up(numer / denom) to an integer; denom > 0."""
    q = (Decimal(int(numer)) / Decimal(int(denom))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def rhu_product(base, mults):
    """round_half_up(base * m1 * m2 * ...) with multipliers applied pre-rounding."""
    x = Decimal(int(base))
    for m in mults:
        x = x * Decimal(str(m))
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
