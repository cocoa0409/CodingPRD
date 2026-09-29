"""Core primitives: errors, logical clock, time helpers, response envelope, store.

Residential Solar Portfolio Servicing API.
Every structural name here is taken from PRD.md (authoritative) / SCAFFOLD.yaml.
"""
import json
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# ---------------------------------------------------------------------------
# Error catalogue (PRD §5 / SCAFFOLD §1.6) — 49 codes
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_AGREEMENT_HOMEOWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_HOMEOWNER_NOT_FOUND": 404,
    "ERR_TARIFF_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_TRUE_UP_NOT_FOUND": 404,
    "ERR_OUTAGE_EVENT_NOT_FOUND": 404,
    "ERR_TRUCK_ROLL_NOT_FOUND": 404,
    "ERR_ROOF_WORK_ORDER_NOT_FOUND": 404,
    "ERR_TRANSFER_CASE_NOT_FOUND": 404,
    "ERR_UCC_FILING_NOT_FOUND": 404,
    "ERR_ELECTION_NOT_FOUND": 404,
    "ERR_WARRANTY_CLAIM_NOT_FOUND": 404,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_TRUE_UP_ALREADY_POSTED": 409,
    "ERR_TRANSFER_ALREADY_OPEN": 409,
    "ERR_ELECTION_ALREADY_OPEN": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_DECOMMISSIONED": 409,
    "ERR_TECHNICIAN_WINDOW_CONFLICT": 409,
    "ERR_ROOF_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_PERIOD": 409,
    "ERR_DUPLICATE_FILING_NUMBER": 409,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_DUPLICATE_TARIFF_CODE": 409,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    "ERR_STALE_OUTAGE_EVENT_VERSION": 412,
    "ERR_ELECTION_WINDOW_CLOSED": 422,
    "ERR_CLOSING_DATE_IN_PAST": 422,
    "ERR_DETECTED_AT_IN_FUTURE": 422,
    "ERR_PERIOD_NOT_ELAPSED": 422,
    "ERR_WARRANTY_WINDOW_EXPIRED": 422,
    "ERR_ROOF_DATES_INVALID": 422,
    "ERR_TITLE_NOT_CLEAR": 422,
    "ERR_ROOF_WORK_IN_PROGRESS": 422,
    "ERR_TRANSFER_IN_PROGRESS": 422,
    "ERR_PERIODS_INCOMPLETE": 422,
    "ERR_TRUCK_ROLL_NOT_CLAIMABLE": 422,
    "ERR_BUYER_FIELD_MISMATCH": 422,
    "ERR_UNAPPLIED_CREDIT_BLOCKS_PURCHASE": 422,
    "ERR_ROOF_WORK_LIMIT_EXCEEDED": 422,
    "ERR_CLAIM_REVISION_LIMIT": 422,
    "ERR_PRODUCT_TERMS_MISMATCH": 422,
    "ERR_CREDIT_CAP_EXCEEDED": 422,
    "ERR_APPROVED_AMOUNT_EXCEEDS_CLAIM": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO-8601 instant into a timezone-aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mm),
                      int(ss) if ss else 0, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    """Parse a strict ISO date (YYYY-MM-DD) into a date, or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD §2.4)."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def days_in_month(year, month):
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def add_years(d, years):
    """Add whole years, clamping day-of-month (Feb 29 -> Feb 28)."""
    y = d.year + years
    try:
        return date(y, d.month, d.day)
    except ValueError:
        return date(y, d.month, days_in_month(y, d.month))


def month_start_instant(year, month):
    return datetime(year, month, 1, tzinfo=timezone.utc)


def next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def month_index(year, month):
    return year * 12 + month


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5) — initialised to 2026-08-01T00:00:00Z on startup.
# ---------------------------------------------------------------------------
class LogicalClock:
    DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self._now = self.DEFAULT

    def now(self):
        return self._now

    def today(self):
        return self._now.date()

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


# ---------------------------------------------------------------------------
# Rounding (PRD §2.6) — ROUND_HALF_UP everywhere, away from zero at midpoint.
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime,)):
        return fmt_instant(obj)
    if isinstance(obj, date):
        return fmt_date(obj)
    raise TypeError(repr(obj))


def dumps(obj):
    return json.dumps(obj, default=_json_default)


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_instant(datetime.now(timezone.utc)),
    }


# ---------------------------------------------------------------------------
# In-memory store — starts completely empty on every boot. No seeding, ever.
# ---------------------------------------------------------------------------
class Store:
    COLLECTIONS = (
        "homeowners", "tariffs", "agreements", "periods", "true_ups",
        "outage_events", "truck_rolls", "roof_work_orders", "transfer_cases",
        "ucc_filings", "elections", "warranty_claims",
    )

    def __init__(self):
        self._seq = 0
        for name in self.COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(record, versioned=True):
    """Attach identity + common fields (PRD §2.4)."""
    record["id"] = new_id()
    record["created_at"] = fmt_instant(clock.now())
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Advance a mutated resource's updated_at and version by exactly one."""
    record["updated_at"] = fmt_instant(clock.now())
    record["version"] = record.get("version", 1) + 1
    return record


def sorted_rows(rows):
    """Default ordering: created_at ascending, insertion sequence as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(record, exclude=()):
    out = {}
    for k, v in record.items():
        if k.startswith("_") or k in exclude:
            continue
        out[k] = v
    return out
