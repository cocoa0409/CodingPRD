"""Core primitives for the Autonomous Trucking Corridor Operations API.

Everything in this module traces to PRD.md:

* §2.2  response envelope  (meta / response_type / data, error_id / message)
* §2.3  pagination         (limit / offset / total_count / has_more)
* §2.5  logical clock      (startup default 2026-09-01T00:00:00Z)
* §2.8  money precision    (Decimal, round half up, 2 decimal places)
* §2.10 common resource properties (id, created_at, updated_at, version)
* §2.11 validation priority order
* §5    error catalogue with HTTP statuses
"""

import random
import string
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Decimal helpers — §2.8: "every derived monetary field is rounded half up to
# exactly 2 decimal places at the moment it is computed."
# ---------------------------------------------------------------------------

TWO = Decimal("0.01")
THREE = Decimal("0.001")


def D(value):
    """Coerce anything numeric into a Decimal without going through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(1 if value else 0)
    if isinstance(value, int):
        return Decimal(value)
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def rhu(value, places=2):
    """ROUND_HALF_UP to `places` decimal places, returned as a Decimal."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def floor_dec(value, places=2):
    """floor(v, places) — the scaffold's `floor(x, n)` notation."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_FLOOR)


def ceil_dec(value, places=2):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_CEILING)


def num(value):
    """Render a Decimal for JSON: integral values become ints, else floats.

    Tests read JSON numbers; a Decimal is serialised through float() so that
    762.28 round trips exactly for two-decimal money figures.
    """
    d = D(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Logical clock — §2.5
# ---------------------------------------------------------------------------

# "The server's startup default clock is exactly 2026-09-01T00:00:00Z."
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

_CLOCK = {"now": None}


def reset_clock():
    _CLOCK["now"] = parse_iso(DEFAULT_CLOCK)


def now():
    if _CLOCK["now"] is None:
        reset_clock()
    return _CLOCK["now"]


def set_clock(value):
    _CLOCK["now"] = parse_iso(value)


def now_iso():
    return to_iso(now())


def epoch_key():
    """Identity of the current ledger epoch, used to scope per-epoch counters."""
    st = active_epoch_start()
    return st if st is not None else DEFAULT_CLOCK


def epoch_day():
    """The current ledger epoch day, counted from the ledger epoch epoch_start."""
    st = active_epoch_start()
    if st is None:
        st = parse_iso(DEFAULT_CLOCK)
    return (now().date() - st.date()).days


# ---------------------------------------------------------------------------
# ISO 8601 UTC with exactly three fractional digits — §2.10
# ---------------------------------------------------------------------------


def parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        dt = parse_iso(dt)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def try_iso(value):
    """Parse and normalise an ISO instant, returning None when unusable."""
    dt = parse_iso(value)
    if dt is None:
        return None
    return to_iso(dt)


def midnight_iso(date_like):
    """An ISO 8601 UTC datetime at midnight, used by standard_inspection_due_date."""
    dt = parse_iso(date_like)
    if dt is None:
        return None
    return to_iso(datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc))


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Identifier and request-id minting — §2.10 / §2.2
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    """Plain UUID, no type prefix and no natural key — §2.10."""
    import uuid
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(18))


# ---------------------------------------------------------------------------
# Epoch / checkpoint registry — §2.5
# ---------------------------------------------------------------------------

_EPOCH = {"checkpoints": []}


def register_checkpoint(row):
    _EPOCH["checkpoints"].append(row)


def active_epoch_start():
    """checkpoint_status ADOPTED wins, else the earliest OPEN checkpoint."""
    cands = [c for c in _EPOCH["checkpoints"] if c.get("checkpoint_status") == "ADOPTED"]
    if cands:
        cands.sort(key=lambda c: c.get("created_at") or "")
        return cands[0].get("epoch_start_at")
    opens = [c for c in _EPOCH["checkpoints"] if c.get("checkpoint_status") == "OPEN"]
    if opens:
        opens.sort(key=lambda c: c.get("created_at") or "")
        return opens[0].get("epoch_start_at")
    return None


def adopted_checkpoint():
    cands = [c for c in _EPOCH["checkpoints"] if c.get("checkpoint_status") == "ADOPTED"]
    if cands:
        cands.sort(key=lambda c: c.get("created_at") or "")
        return cands[0]
    opens = [c for c in _EPOCH["checkpoints"] if c.get("checkpoint_status") == "OPEN"]
    if opens:
        opens.sort(key=lambda c: c.get("created_at") or "")
        return opens[0]
    return None


def hours_per_epoch():
    cp = adopted_checkpoint()
    if cp is None:
        return 24
    return cp.get("hours_per_epoch", 24)


def epoch_window():
    cp = adopted_checkpoint()
    if cp is None:
        return (None, None)
    return (parse_iso(cp.get("epoch_start_at")), parse_iso(cp.get("epoch_end_at")))


# ---------------------------------------------------------------------------
# Errors — §2.11 priority order and §5 statuses
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CORRIDOR_NOT_FOUND": 404,
    "ERR_RUN_PLAN_NOT_FOUND": 404,
    "ERR_TERMINAL_NOT_FOUND": 404,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 422,
    "ERR_CORRIDOR_RESTRICTED": 409,
    "ERR_CORRIDOR_FROZEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_RUN_PLAN_TERMINAL": 409,
    "ERR_CALIBRATION_FAILED": 409,
    "ERR_LOAD_SECUREMENT_FAILED": 409,
    "ERR_SAFETY_CASE_STALE": 409,
    "ERR_WEATHER_RESTRICTED": 409,
    "ERR_BLOCKED_BY_INCIDENT": 409,
    "ERR_ROUTE_NOT_VALIDATED": 409,
    "ERR_MAINTENANCE_OVERDUE": 409,
    "ERR_READINESS_CHECK_FAILED": 409,
    "ERR_RUN_PLAN_OVERLAP": 409,
    "ERR_APRON_OVERLAP": 409,
    "ERR_APRON_CAPACITY_EXCEEDED": 409,
    "ERR_MONITOR_OVERLAP": 409,
    "ERR_COVERAGE_DATE_REQUIRED": 422,
    "ERR_MULTI_DAY_NOT_ALLOWED": 422,
    "ERR_HOLD_WINDOW_INVERTED": 422,
    "ERR_COMMITMENT_CAPACITY_EXHAUSTED": 409,
    "ERR_RATE_BELOW_COMMITMENT_FLOOR": 422,
    "ERR_NO_ELIGIBLE_COMMITMENT": 409,
    "ERR_CHARGE_NOT_ALLOWED": 422,
    "ERR_HOURS_BUDGET_EXCEEDED": 409,
    "ERR_OUTSIDE_EPOCH_WINDOW": 422,
    "ERR_REVIEW_WINDOW_LAPSED": 409,
    "ERR_DISPATCH_WINDOW_CONFLICT": 409,
    "ERR_INVALID_ROUTE": 422,
    "ERR_INVALID_TRAILER_COUNT": 422,
    "ERR_INVALID_VERSION": 422,
    "ERR_INVALID_INSPECTION_INTERVAL": 422,
    "ERR_DUPLICATE_OPERATOR": 422,
    "ERR_CORRECTIVE_ACTION_REQUIRED": 409,
    "ERR_CARRIER_HAS_LIVE_RUN_PLANS": 409,
    "ERR_RUN_PLAN_IN_TRANSIT": 409,
    "ERR_NO_APPROVED_HANDOFF_WINDOW": 409,
    "ERR_HOLD_NOT_ACTIVE": 409,
    "ERR_VGM_VERIFICATION_FAILED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_REPRO_NOT_REPLICATION": 422,
    "ERR_MISSING_LOGS": 422,
}

# §2.11: auth → authorisation → path existence → reference resolution →
#        posture → row state → domain rules.
PRIORITY_AUTH = 1
PRIORITY_UNAUTHORIZED = 2
PRIORITY_EXISTENCE = (3, 8)
PRIORITY_REFERENCE = 9
PRIORITY_POSTURE = (10, 11)
PRIORITY_STATE = (12, 13)
PRIORITY_DOMAIN = 14


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        super().__init__(self.message)