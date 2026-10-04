"""In-memory data store, logical clock, and shared helpers.

The store starts EMPTY on every boot -- no seeding of any kind. Every entity
a test needs is constructed through the declared API surface.

Logical clock (PRD 2.5): the system never consults wall-clock time for
time-dependent rules. Startup default is exactly 2026-09-01T00:00:00Z and
a FranchisorAdmin may advance it via POST /franchise-system/_clock/set_current_utc.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 40

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
_clock_dt = None  # datetime (aware, UTC)


def _parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Current logical clock instant (aware UTC datetime)."""
    global _clock_dt
    if _clock_dt is None:
        _clock_dt = _parse_dt(_CLOCK_DEFAULT)
    return _clock_dt


def set_clock(value):
    global _clock_dt
    _clock_dt = _parse_dt(value)


def clock_date():
    return clock_now().date()


def iso_ts(dt=None):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt or clock_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD) into a ``date``."""
    return date.fromisoformat(str(value).strip()[:10])


# ---------------------------------------------------------------------------
# Money / rounding helpers (PRD 2.6: whole cents, round-half-up)
# ---------------------------------------------------------------------------

_CENT = Decimal("1")


def dec(value):
    """Convert a JSON number to Decimal preserving input precision."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_cents(value):
    """Round a Decimal to whole cents using ROUND_HALF_UP. Returns int."""
    return int(dec(value).quantize(_CENT, rounding=ROUND_HALF_UP))


def round_half_up_int(value):
    """Round a Decimal to an integer using ROUND_HALF_UP. Returns int."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_seq = 0

DB = {
    "sites": [],
    "operators": [],
    "stores": [],
    "agreements": [],
    "subleases": [],
    "sales_reports": [],
    "rent_charges": [],
    "fund_assessments": [],
    "reinvestment_obligations": [],
    "default_events": [],
    "advertising_funds": [],
    "coop_assessments": [],
    "capacity_reviews": [],
    # per-fund ledger: fund_id -> {"credits": [(amount, fee)], "disbursements": [amount]}
    "fund_ledger": {},
}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def make_entity(kind, fields):
    """Create a new entity dict with common system fields (PRD 2.4)."""
    now = iso_ts()
    ent = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    DB[kind].append(ent)
    return ent


def touch(ent):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4)."""
    ent["updated_at"] = iso_ts()
    ent["version"] += 1


def find(kind, entity_id):
    for ent in DB[kind]:
        if ent["id"] == entity_id:
            return ent
    return None


def public(ent):
    """Strip internal bookkeeping keys from an entity for serialization."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Derived operator aggregates (PRD 2.10: recomputed synchronously)
# ---------------------------------------------------------------------------

def stores_of_operator(operator_id):
    return [s for s in DB["stores"] if s["operator_id"] == operator_id]


def recompute_operator_aggregates(operator):
    """Recompute stores_operated_count and delinquency_balance_cents."""
    op_id = operator["id"]
    stores = stores_of_operator(op_id)
    operator["stores_operated_count"] = sum(1 for s in stores if s["status"] == "OPEN")
    store_ids = {s["id"] for s in stores}
    delinquency = 0
    for charge in DB["rent_charges"]:
        if charge["store_id"] in store_ids and charge["status"] == "OPEN":
            delinquency += charge["selected_rent_cents"] - charge["amount_paid_cents"]
    for fa in DB["fund_assessments"]:
        if fa["store_id"] in store_ids and fa["status"] == "OPEN":
            delinquency += fa["royalty_cents"] + fa["ad_fund_cents"]
    operator["delinquency_balance_cents"] = delinquency


def store_delinquency(store_id):
    """Delinquent OPEN charges on one store (rent unpaid + open assessments)."""
    total = 0
    for charge in DB["rent_charges"]:
        if charge["store_id"] == store_id and charge["status"] == "OPEN":
            total += charge["selected_rent_cents"] - charge["amount_paid_cents"]
    for fa in DB["fund_assessments"]:
        if fa["store_id"] == store_id and fa["status"] == "OPEN":
            total += fa["royalty_cents"] + fa["ad_fund_cents"]
    return total


# ---------------------------------------------------------------------------
# Fund ledger
# ---------------------------------------------------------------------------

def fund_credit(fund, amount_cents):
    """Credit a fund: balance += amount - round_half_up(amount * admin_fee_rate)."""
    fee = round_half_up_cents(dec(amount_cents) * dec(fund["admin_fee_rate"]))
    ledger = DB["fund_ledger"].setdefault(fund["id"], {"credits": [], "disbursements": []})
    ledger["credits"].append((int(amount_cents), fee))
    fund["balance_cents"] += int(amount_cents) - fee


def fund_debit(fund, amount_cents):
    ledger = DB["fund_ledger"].setdefault(fund["id"], {"credits": [], "disbursements": []})
    ledger["disbursements"].append(int(amount_cents))
    fund["balance_cents"] -= int(amount_cents)


# ---------------------------------------------------------------------------
# Lazy temporal sweeps (PRD 2.5: the logical clock governs every
# time-dependent rule; transitions fire automatically when it passes).
# ---------------------------------------------------------------------------

def temporal_sweep():
    """Apply clock-driven transitions: agreement/sublease expiry, obligation breach."""
    today = clock_date()
    for ag in DB["agreements"]:
        if ag["status"] == "ACTIVE" and today > parse_date(ag["term_end_date"]):
            ag["status"] = "EXPIRED"
            touch(ag)
    for sub in DB["subleases"]:
        if sub["status"] == "ACTIVE" and today > parse_date(sub["end_date"]):
            sub["status"] = "EXPIRED"
            touch(sub)
    for ob in DB["reinvestment_obligations"]:
        if ob["status"] == "PENDING" and today > parse_date(ob["deadline_date"]):
            ob["status"] = "BREACHED"
            touch(ob)


# ---------------------------------------------------------------------------
# Misc validation helpers
# ---------------------------------------------------------------------------

_PERIOD_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_YEAR_RE = re.compile(r"^\d{4}$")


def is_period_month(value):
    return isinstance(value, str) and bool(_PERIOD_MONTH_RE.match(value))


def is_year(value):
    return isinstance(value, str) and bool(_YEAR_RE.match(value))
