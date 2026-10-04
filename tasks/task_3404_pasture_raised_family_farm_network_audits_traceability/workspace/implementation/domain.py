"""Cross-entity business logic.

Capacity arithmetic (PRD 2.8), certification derivation (PRD 2.7), forecast
variants and commitment caps (PRD 3.7), route load reconciliation (PRD 2.9),
suspension / removal cascades (PRD 3.4), clock sweeps (PRD 2.5), farmer
payment and commitment fill arithmetic (PRD 3.8), plus left-to-right
existence lookups (PRD 2.6).
"""
import uuid
from datetime import timedelta, datetime, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import constants as C
import store
from clock import now, parse_date
from errors import ApiError


def new_id():
    """Server-minted UUID, no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Existence lookups (PRD 2.6; each raises its catalogue 404)
# ---------------------------------------------------------------------------

def get_farm_or_404(fid):
    f = store.farms.get(fid) if isinstance(fid, str) else None
    if f is None:
        raise ApiError("ERR_FARM_NOT_FOUND", 404, "farm not found")
    return f


def get_audit_or_404(aid):
    a = store.audits.get(aid) if isinstance(aid, str) else None
    if a is None:
        raise ApiError("ERR_AUDIT_NOT_FOUND", 404, "audit not found")
    return a


def get_ca_or_404(cid):
    ca = store.corrective_actions.get(cid) if isinstance(cid, str) else None
    if ca is None:
        raise ApiError("ERR_CA_NOT_FOUND", 404, "corrective action not found")
    return ca


def get_incident_or_404(iid):
    i = store.incidents.get(iid) if isinstance(iid, str) else None
    if i is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", 404, "incident not found")
    return i


def get_route_or_404(rid):
    r = store.routes.get(rid) if isinstance(rid, str) else None
    if r is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND", 404, "route not found")
    return r


def get_stop_or_404(route, seq_raw):
    try:
        seq = int(seq_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_STOP_NOT_FOUND", 404, "stop not found")
    for s in route["stops"]:
        if s["stop_sequence"] == seq:
            return s
    raise ApiError("ERR_STOP_NOT_FOUND", 404, "stop not found")


def get_lot_or_404(lid):
    lot = store.lots.get(lid) if isinstance(lid, str) else None
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", 404, "lot not found")
    return lot


def get_carton_or_404(code):
    c = store.cartons.get(code) if isinstance(code, str) else None
    if c is None:
        raise ApiError("ERR_CARTON_NOT_FOUND", 404, "carton not found")
    return c


def get_commitment_or_404(cid):
    cm = store.commitments.get(cid) if isinstance(cid, str) else None
    if cm is None:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND", 404, "commitment not found")
    return cm


def get_settlement_or_404(sid):
    s = store.settlement_runs.get(sid) if isinstance(sid, str) else None
    if s is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND", 404, "settlement run not found")
    return s


# ---------------------------------------------------------------------------
# Capacity (PRD 2.8): floor each component, then min. Decimal arithmetic so
# e.g. barn_sqft = 2.4 yields exactly 2 (float 2.4/1.2 floors to 1).
# ---------------------------------------------------------------------------

def compute_effective_bird_capacity(pasture_sqft, barn_sqft, nest_box_count):
    pasture_cap = (Decimal(str(pasture_sqft)) / C.MIN_PASTURE_SQFT_PER_BIRD
                   ).to_integral_value(rounding=ROUND_FLOOR)
    barn_cap = (Decimal(str(barn_sqft)) / C.MIN_BARN_SQFT_PER_BIRD
                ).to_integral_value(rounding=ROUND_FLOOR)
    nest_cap = int(nest_box_count) * C.BIRDS_PER_NEST_BOX
    return int(min(pasture_cap, barn_cap, nest_cap))


# ---------------------------------------------------------------------------
# Certification derivation (PRD 2.7): pure function of (status,
# last_passed_audit_at, now); evaluated in the pinned order.
# ---------------------------------------------------------------------------

def derive_certification_status(farm):
    if farm["status"] == "REMOVED":
        return "DECERTIFIED"
    last = farm["last_passed_audit_at"]
    if last is None:
        return "CERTIFICATION_PENDING"
    if now() > last + timedelta(days=C.CERT_VALIDITY_DAYS):
        return "CERT_LAPSED"
    return "CERTIFIED"


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

def find_covering_contract(farm_id, day, require_active):
    """The farm's contract with the LATEST start_date covering `day`
    (start_date <= day <= end_date). Any status unless require_active."""
    best = None
    for c in store.contracts.values():
        if c["farm_id"] != farm_id:
            continue
        if require_active and c["status"] != "ACTIVE":
            continue
        if c["_start"] <= day <= c["_end"]:
            if best is None or (c["_start"], c["_seq"]) > (best["_start"], best["_seq"]):
                best = c
    return best


# ---------------------------------------------------------------------------
# Forecasts and commitment caps (PRD 3.7). Floor only after the full product.
# ---------------------------------------------------------------------------

def forecast_variants(declared_bird_count, season, weather_severity):
    def _variant(table):
        eggs = (Decimal(declared_bird_count) * C.LAY_RATE[season]
                * table[weather_severity] * C.DAYS_PER_WEEK)
        return int((eggs / C.EGGS_PER_DOZEN).to_integral_value(rounding=ROUND_FLOOR))
    return _variant(C.WEATHER_OPTIMISTIC), _variant(C.WEATHER_CONSERVATIVE)


def commitment_cap(conservative_dozens):
    return int((Decimal(conservative_dozens) * C.MAX_COMMIT_RATIO
                ).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Route load reconciliation (PRD 2.9) and the stop-skip cascade (PRD 3.4)
# ---------------------------------------------------------------------------

def recompute_route_load(route):
    committed = 0
    for s in route["stops"]:
        if s["status"] == "SCHEDULED":
            committed += s["planned_cases"]
        elif s["status"] == "COLLECTED":
            committed += s["collected_cases"]
    route["committed_cases"] = committed
    route["available_cases"] = route["capacity_cases"] - committed


def skip_scheduled_stops_for_farm(farm_id):
    """Every SCHEDULED stop naming the farm on any PLANNED route -> SKIPPED;
    each affected route recomputes and bumps its version once."""
    ts = now()
    for r in store.routes.values():
        if r["status"] != "PLANNED":
            continue
        changed = False
        for s in r["stops"]:
            if s["farm_id"] == farm_id and s["status"] == "SCHEDULED":
                s["status"] = "SKIPPED"
                changed = True
        if changed:
            recompute_route_load(r)
            r["version"] += 1
            r["updated_at"] = ts


# ---------------------------------------------------------------------------
# Farm cascades (PRD 3.4)
# ---------------------------------------------------------------------------

def suspend_farm(farm):
    farm["status"] = "SUSPENDED"
    farm["version"] += 1
    farm["updated_at"] = now()
    skip_scheduled_stops_for_farm(farm["id"])


def suspend_farm_if_active_or_probation(farm):
    if farm["status"] in ("ACTIVE", "PROBATION"):
        suspend_farm(farm)


def probate_farm_if_active(farm):
    if farm["status"] == "ACTIVE":
        farm["status"] = "PROBATION"
        farm["version"] += 1
        farm["updated_at"] = now()


def run_removal_cascade(farm, reason):
    """The six-step REMOVAL cascade of PRD 3.4, in order."""
    ts = now()
    today = ts.date()
    # (1) farm itself
    farm["status"] = "REMOVED"
    farm["removal_reason"] = reason
    farm["version"] += 1
    farm["updated_at"] = ts
    # (2) ACTIVE contract -> TERMINATED
    for c in store.contracts.values():
        if c["farm_id"] == farm["id"] and c["status"] == "ACTIVE":
            c["status"] = "TERMINATED"
            c["version"] += 1
            c["updated_at"] = ts
    # (3) ACTIVE commitments with week_start strictly after today -> CANCELLED
    for cm in store.commitments.values():
        if (cm["farm_id"] == farm["id"] and cm["status"] == "ACTIVE"
                and cm["_week_start"] > today):
            cm["status"] = "CANCELLED"
            cm["version"] += 1
            cm["updated_at"] = ts
    # (4) SCHEDULED stops on PLANNED routes -> SKIPPED (loads recomputed)
    skip_scheduled_stops_for_farm(farm["id"])
    # (5) SCHEDULED audits -> CANCELLED
    audit_ids = set()
    for a in store.audits.values():
        if a["farm_id"] == farm["id"]:
            audit_ids.add(a["id"])
            if a["status"] == "SCHEDULED":
                a["status"] = "CANCELLED"
                a["version"] += 1
                a["updated_at"] = ts
    # (6) OPEN / OVERDUE / SUBMITTED corrective actions -> CANCELLED
    for ca in store.corrective_actions.values():
        if ca["audit_id"] in audit_ids and ca["status"] in ("OPEN", "OVERDUE", "SUBMITTED"):
            ca["status"] = "CANCELLED"
            ca["version"] += 1
            ca["updated_at"] = ts


# ---------------------------------------------------------------------------
# Payments and commitment fill (PRD 3.8)
# ---------------------------------------------------------------------------

def payment_subline_cents(dozens, rate_cents, grade):
    """round_half_up(dozens * rate * QUALITY_MULT[grade]) per grade subline,
    BEFORE summation (pinned rounding order, PRD 2.10)."""
    amount = Decimal(dozens) * Decimal(rate_cents) * C.QUALITY_MULT[grade]
    return int(amount.to_integral_value(rounding=ROUND_HALF_UP))


def fill_threshold(committed_dozens):
    return int((Decimal(committed_dozens) * C.MIN_FILL_RATE
                ).to_integral_value(rounding=ROUND_FLOOR))


def commitment_fill_rate(delivered, committed):
    q = (Decimal(delivered) / Decimal(committed)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def week_bounds(week_start_date):
    """Half-open [week_start, week_start + 7 days) as aware UTC datetimes."""
    start = datetime(week_start_date.year, week_start_date.month,
                     week_start_date.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=C.DAYS_PER_WEEK)


# ---------------------------------------------------------------------------
# Clock sweeps (PRD 2.5), fired in pinned order on every advance.
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    ts = now()
    # (1) SCHEDULED audits past scheduled_for + 7 days -> EXPIRED
    for a in store.audits.values():
        if (a["status"] == "SCHEDULED"
                and ts > a["_scheduled_dt"] + timedelta(days=C.AUDIT_WINDOW_LATE_DAYS)):
            a["status"] = "EXPIRED"
            a["version"] += 1
            a["updated_at"] = ts
    # (2) OPEN / SUBMITTED corrective actions strictly past due_at -> OVERDUE,
    #     with severity escalations against the farm
    for ca in list(store.corrective_actions.values()):
        if ca["status"] in ("OPEN", "SUBMITTED") and ts > ca["due_at"]:
            ca["status"] = "OVERDUE"
            ca["version"] += 1
            ca["updated_at"] = ts
            audit = store.audits.get(ca["audit_id"])
            farm = store.farms.get(audit["farm_id"]) if audit else None
            if farm is None:
                continue
            if ca["severity"] == "CRITICAL":
                suspend_farm_if_active_or_probation(farm)
            elif ca["severity"] == "MAJOR":
                probate_farm_if_active(farm)
            # MINOR: no farm status change
    # (3) certification lapse is a pure derivation (PRD 2.7): reads re-derive
    #     CERT_LAPSED from last_passed_audit_at + 365 days, so nothing writes.


# ---------------------------------------------------------------------------
# List ordering: created_at ascending (PRD 2.3), insertion order breaks ties.
# ---------------------------------------------------------------------------

def sorted_page(records, limit, offset):
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total
