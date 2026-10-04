"""In-memory data store and logical clock.

Nothing is seeded at import time: every collection starts empty and every row
is created by a caller through a declared endpoint.  State lives only in this
process, so a fresh `start.sh` invocation always begins from an empty store.
"""

import uuid
from datetime import datetime, timedelta, timezone

import constants as C

# --- collections -------------------------------------------------------------
sites = {}
customers = {}
ppas = {}
service_plans = {}
fuel_deliveries = {}
settlement_lines = {}
accruals = {}
allowances = {}
transitions = {}

# --- logical clock -----------------------------------------------------------
_clock = None


def _parse_iso(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock():
    """Current logical instant; starts at the documented default and never
    falls back to wall-clock time."""
    global _clock
    if _clock is None:
        _clock = _parse_iso(C.DEFAULT_CLOCK_ISO)
    return _clock


def set_clock(value):
    global _clock
    _clock = _parse_iso(value)
    return _clock


def parse_dt(value):
    return _parse_iso(value)


def ts(dt=None):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        dt = clock()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return ts(clock())


def advance(dt, **kwargs):
    return dt + timedelta(**kwargs)


def days_between(start, end):
    """(end - start) expressed in whole days, truncated toward zero."""
    if start is None or end is None:
        return 0
    delta = end - start
    return int(delta.total_seconds() // 86400)


def new_id():
    return str(uuid.uuid4())


_sequence = 0


def next_seq():
    """Monotonic insertion counter.

    The logical clock is frozen between calls, so many rows share one
    `created_at`; ordering ties are broken on this counter -- an insertion
    order -- and never on an identifier (PRD 3.9).
    """
    global _sequence
    _sequence += 1
    return _sequence


def create(collection, record):
    """Persist a new row: id, created_at, updated_at, version start at 1."""
    stamp = now_iso()
    record["id"] = new_id()
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    record["_seq"] = next_seq()
    collection[record["id"]] = record
    return record


def touch(record):
    """Mark a row as modified: refresh updated_at and advance version by one."""
    if record is None:
        return record
    record["updated_at"] = now_iso()
    record["version"] = int(record.get("version", 0)) + 1
    return record


# --- lookups -----------------------------------------------------------------
def get_site(site_id):
    return sites.get(site_id)


def get_customer(customer_id):
    return customers.get(customer_id)


def get_ppa(ppa_id):
    return ppas.get(ppa_id)


def get_service_plan(plan_id):
    return service_plans.get(plan_id)


def get_delivery(delivery_id):
    return fuel_deliveries.get(delivery_id)


def get_line(line_id):
    return settlement_lines.get(line_id)


def get_accrual(accrual_id):
    return accruals.get(accrual_id)


def get_allowance(allowance_id):
    return allowances.get(allowance_id)


def get_transition(transition_id):
    return transitions.get(transition_id)


def site_ppas(site_id):
    return [p for p in ppas.values() if p["site_id"] == site_id]


def customer_ppas(customer_id):
    return [p for p in ppas.values() if p["customer_id"] == customer_id]


def ppa_plans(ppa_id):
    return [s for s in service_plans.values() if s["ppa_id"] == ppa_id]


def site_plans(site_id):
    out = []
    for plan in service_plans.values():
        ppa = ppas.get(plan["ppa_id"])
        if ppa is not None and ppa["site_id"] == site_id:
            out.append(plan)
    return out


def site_deliveries(site_id):
    return [d for d in fuel_deliveries.values() if d["site_id"] == site_id]


def ppa_lines(ppa_id):
    return [ln for ln in settlement_lines.values() if ln["ppa_id"] == ppa_id]


def ppa_accruals(ppa_id):
    return [a for a in accruals.values() if a["ppa_id"] == ppa_id]


def ppa_allowances(ppa_id):
    return [a for a in allowances.values() if a["ppa_id"] == ppa_id]


def ppa_transitions(ppa_id):
    return [t for t in transitions.values() if t["ppa_id"] == ppa_id]


def by_created(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


def one(rows):
    return rows[0] if rows else None


# --- pagination --------------------------------------------------------------
def paginate(rows, args):
    """Apply the scaffold's limit/offset contract to an ordered list."""
    try:
        limit = int(args.get("limit", C.PAGINATION_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = C.PAGINATION_DEFAULT_LIMIT
    try:
        offset = int(args.get("offset", C.PAGINATION_DEFAULT_OFFSET))
    except (TypeError, ValueError):
        offset = C.PAGINATION_DEFAULT_OFFSET
    if limit < C.PAGINATION_MIN_LIMIT:
        limit = C.PAGINATION_MIN_LIMIT
    if limit > C.PAGINATION_MAX_LIMIT:
        limit = C.PAGINATION_MAX_LIMIT
    if offset < 0:
        offset = 0
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
