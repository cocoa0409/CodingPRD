"""In-memory data store, logical clock, and timestamp rendering.

The store is module-level dicts; a fresh process (start.sh) always boots with
empty state and the logical clock at the PRD-mandated default. No seeding.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

BOOT_CLOCK_RAW = "2026-09-01T00:00:00Z"


def parse_iso_datetime(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Naive values are interpreted as UTC. Raises ValueError on bad input.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        if t.endswith("Z"):
            dt = datetime.fromisoformat(t[:-1] + "+00:00")
        else:
            raise ValueError("unparseable datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(s):
    """Parse an ISO 8601 calendar date string. Raises ValueError on bad input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s.strip())


def _frac_len_of(raw):
    i = raw.find(".")
    if i < 0:
        return 0
    j = i + 1
    while j < len(raw) and raw[j].isdigit():
        j += 1
    return j - i - 1


# ---------------------------------------------------------------------------
# The store. Everything lives here; nothing is persisted across processes.
# ---------------------------------------------------------------------------
db = {
    # logical clock
    "clock_raw": BOOT_CLOCK_RAW,               # as last supplied (verbatim)
    "clock_dt": parse_iso_datetime(BOOT_CLOCK_RAW),
    "clock_frac_len": _frac_len_of(BOOT_CLOCK_RAW),
    "spot_prices": {},                          # commodity/metal -> int cents
    # receipt-order counter for deterministic tie-breaking
    "seq": 0,
    # entities
    "denominations": {},        # code -> entity
    "fed_orders": {},           # id -> entity
    "lots": {},                 # id -> entity
    "runs": {},                 # id -> entity
    "programs": {},             # id -> entity
    "products": {},             # id -> entity
    "collectors": {},           # id -> entity
    "orders": {},               # id -> entity
    "subscriptions": {},        # id -> entity
    "invoices": {},             # id -> entity
    "bullion_issues": {},       # id -> entity
    "authorized_purchasers": {},  # id -> entity
    "allocations": {},          # id -> entity
    "error_cases": {},          # id -> entity
}


def next_seq():
    db["seq"] += 1
    return db["seq"]


def new_id():
    # Dashed UUID form (str of uuid4) — never .hex.
    return str(uuid.uuid4())


def now_dt():
    return db["clock_dt"]


def now_raw():
    return db["clock_raw"]


def set_clock(raw, dt):
    db["clock_raw"] = raw
    db["clock_dt"] = dt
    db["clock_frac_len"] = _frac_len_of(raw)


def render_system_ts(dt):
    """System family: created_at/updated_at/api_request_timestamp —
    ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def render_like_clock(dt):
    """Domain family computed timestamp: render the way the logical clock
    reads (same fractional-digit precision as the supplied clock value)."""
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    n = db["clock_frac_len"]
    if n <= 0:
        return base + "Z"
    frac = "{:06d}".format(dt.microsecond)
    if n <= 6:
        frac = frac[:n]
    else:
        frac = frac + "0" * (n - 6)
    return base + "." + frac + "Z"


def mint_entity(fields):
    """Attach common system fields to a freshly created entity."""
    e = dict(fields)
    e["id"] = new_id()
    e["created_at"] = db["clock_dt"]
    e["updated_at"] = db["clock_dt"]
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def bump(entity):
    """Every mutation increments version by exactly 1 and re-stamps."""
    entity["version"] += 1
    entity["updated_at"] = db["clock_dt"]


def sort_created(items):
    """created_at ascending; ties broken by server receipt order."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def add_months(d, months):
    """Advance a date by whole months, clamping the day to the month length."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    if m == 12:
        last = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(y, m + 1, 1) - timedelta(days=1)
    return date(y, m, min(d.day, last.day))
