"""Core plumbing: in-memory store, logical clock, errors, envelope, dt helpers."""
import re
import uuid
from datetime import datetime, date, timedelta, timezone

from flask import jsonify

# ---------------------------------------------------------------------------
# In-memory store (blank slate on every process boot; never seeded)
# ---------------------------------------------------------------------------
STORE = {
    "brands": {},
    "product_lines": {},
    "formulations": {},
    "manufacturers": {},
    "grants": {},
    "distributors": {},
    "markets": {},
    "registrations": {},
    "assignments": {},
    "packs": {},
    "price_lists": {},
    "promotions": {},
    "cases": {},
    "use_cases": {},
    "reports": {},
    "clock": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
    "seq": 0,
}

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def fail(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# Error id -> http status (PRD §5 catalog)
ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SUBMITTER_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_NO_EFFECTIVE_PRICE": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_DISTRIBUTOR_NOT_APPROVED": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    "ERR_REGISTRATION_EXPIRED": 409,
    "ERR_PROMO_WINDOW_CLOSED": 409,
    "ERR_GRANT_EXPIRED": 409,
    "ERR_BRAND_IN_LOCKDOWN": 409,
    "ERR_POSTURE_CRITICAL": 409,
    "ERR_MANUFACTURER_NOT_QUALIFIED": 409,
    "ERR_COMPARTMENT_SCOPE_EXCEEDED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_AUDITOR_CONFLICT": 409,
    "ERR_VOC_REGIME_MISMATCH": 422,
    "ERR_GENERICIZATION_RISK": 422,
    "ERR_RECENT_BREACH": 409,
    "ERR_LOCKDOWN_CONDITIONS_UNMET": 409,
    "ERR_WINDOW_INVALID": 422,
    "ERR_EXCLUSIVE_OVERLAP": 409,
    "ERR_PERIOD_NOT_COMPLETED": 422,
    "ERR_CLOCK_REGRESSION": 400,
    "ERR_DUPLICATE_LINE_CODE": 409,
    "ERR_CORE_LINE_EXISTS": 409,
    "ERR_CORE_LINE_IMMUTABLE": 409,
    "ERR_MARKET_CODE_EXISTS": 409,
    "ERR_CHANNEL_NOT_SERVED": 422,
    "ERR_CHANNEL_NOT_ALLOWED": 422,
    "ERR_CHANNEL_OUTSIDE_LINE_SCOPE": 422,
    "ERR_CELL_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_REPORT": 409,
    "ERR_REGISTRATION_EXISTS": 409,
    "ERR_SCOPE_NOT_SUBSET": 422,
    "ERR_INSUFFICIENT_COMPONENTS": 422,
    "ERR_COMPONENT_LIMIT_EXCEEDED": 422,
    "ERR_MAP_ABOVE_LIST": 422,
    "ERR_FORMULATION_LINE_MISMATCH": 422,
    "ERR_PACK_LINE_MISMATCH": 422,
    "ERR_MARKET_IN_USE": 409,
    "ERR_MARKET_NOT_OPEN": 409,
    "ERR_FORMULATION_NOT_SEALED": 409,
    "ERR_FORMULATION_NOT_COMPARTMENTALIZED": 409,
    "ERR_REGISTRATION_NOT_ACTIVE": 409,
    "ERR_NO_PRICE_LIST": 409,
    "ERR_NO_PRODUCIBLE_PACK_FORMAT": 409,
    "ERR_PRICE_LISTS_OUTSTANDING": 409,
    "ERR_LINE_STAGE_TOO_EARLY": 409,
    "ERR_LINE_NOT_LAUNCHED": 409,
    "ERR_EQUITY_BUDGET_EXCEEDED": 422,
    "ERR_CORE_IDENTITY_DILUTION": 422,
    "ERR_PROMO_DEPTH_EXCEEDS_CAP": 422,
    "ERR_BELOW_MAP_PRICE": 422,
    "ERR_PROMO_TOO_FREQUENT": 422,
    "ERR_PROMO_GAP_VIOLATION": 422,
    "ERR_PROMO_BUDGET_EXCEEDED": 409,
}


def err(error_id, message=None):
    fail(error_id, ERROR_HTTP[error_id], message)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def new_request_id():
    return "req_" + uuid.uuid4().hex[:22].upper()


def _meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def ok(data, response_type="object", code=200, pagination=None):
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def err_response(error_id, http_status, message=None):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


# ---------------------------------------------------------------------------
# Logical clock helpers
# ---------------------------------------------------------------------------
def now():
    return STORE["clock"]


def now_iso():
    return fmt_dt(now())


def today():
    return now().date()


def set_clock(target):
    STORE["clock"] = target


def next_seq():
    STORE["seq"] += 1
    return STORE["seq"]


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_datetime(s):
    """Parse an ISO 8601 UTC datetime string. Returns aware datetime or None."""
    if not isinstance(s, str):
        return None
    m = _DT_RE.match(s.strip())
    if not m:
        return None
    y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micros = 0
    if frac:
        digits = frac[1:]
        micros = int((digits + "000000")[:6])
    tzs = m.group(8)
    if tzs is None:
        return None  # must be UTC-qualified
    if tzs in ("Z", "z"):
        tz = timezone.utc
    else:
        sign = 1 if tzs[0] == "+" else -1
        tzdigits = tzs[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(tzdigits[:2]), minutes=int(tzdigits[2:])))
    try:
        dt = datetime(y, mo, d, h, mi, sec, micros, tzinfo=tz)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict YYYY-MM-DD calendar date. Returns date or None."""
    if not isinstance(s, str):
        return None
    m = _DATE_RE.match(s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_month(s):
    """Validate YYYY-MM period string. Returns normalized 'YYYY-MM' or None."""
    if not isinstance(s, str):
        return None
    m = _MONTH_RE.match(s.strip())
    if not m:
        return None
    mm = int(m.group(2))
    if mm < 1 or mm > 12:
        return None
    return "%04d-%02d" % (int(m.group(1)), mm)


def current_month():
    n = now()
    return "%04d-%02d" % (n.year, n.month)


def trailing_window_months(count):
    """The `count` calendar months strictly before the current logical month."""
    n = now()
    y, m = n.year, n.month
    out = []
    for _ in range(count):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        out.append("%04d-%02d" % (y, m))
    return out


def cmp_sec(a, b):
    """Compare two datetimes at second precision: -1, 0, 1."""
    ka = a.replace(microsecond=0)
    kb = b.replace(microsecond=0)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Rounding (PRD §2.8): half-up via Decimal; floor for the dilution refund
# ---------------------------------------------------------------------------
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(numer, denom=1):
    """round_half_up(numer / denom) to a whole integer."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_half_up_bps(numer, denom):
    return round_half_up_cents(numer, denom)


def pct_of(amount_cents, pct):
    """round_half_up(amount * pct / 100) in whole cents; pct may have 2 decimals."""
    p = Decimal(str(pct))
    q = (Decimal(amount_cents) * p / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------
def stamp_new(entity):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Bump updated_at/version; caller decides whether a real mutation happened."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def public(entity, fields):
    return {k: entity.get(k) for k in fields}


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
