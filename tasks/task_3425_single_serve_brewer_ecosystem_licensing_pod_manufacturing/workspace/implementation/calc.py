"""Calculation rules: royalty brackets, velocity/slow-mover, household model,
brewer subsidy snapshot, capacity windows, and lazy clock evaluations."""
import calendar
import math
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, get_clock
from helpers import parse_dt_val, touch

PER_PERSON_PODS = 30
DORMANCY_DAYS = 60
DEFECT_HARD_MAX_PPM = 500
DEFECT_SOFT_MAX_PPM = 200
EXCLUSIVITY_DISCOUNT_PCT = 8
QUALITY_PENALTY_PCT = 10
UNLICENSED_SHARE_THRESHOLD_PCT = 15
UNLICENSED_DISCOUNT_PCT = 5
SUBSIDY_CAP_CENTS = 20000
# 40 pods/brewer-month * 18 cents margin * 0.5 recovery / 24 months = 15 cents
RECOVERABLE_PER_BREWER_CENTS = 15
SLOW_MOVER_FLOOR_UNITS_90D = 50000
SLOW_MOVER_MIN_AGE_DAYS = 90

_C0 = Decimal("1")
_C2 = Decimal("0.01")


def q0(x):
    return int(Decimal(x).quantize(_C0, rounding=ROUND_HALF_UP))


def q2(x):
    return Decimal(x).quantize(_C2, rounding=ROUND_HALF_UP)


def add_months(dt, months):
    idx = dt.year * 12 + (dt.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def window_days(ws, we):
    secs = (we - ws).total_seconds()
    return max(1, math.ceil(secs / 86400))


# ---------------------------------------------------------------- lazy clocks
def eval_agreement_lazy(agr, persist):
    """ACTIVE -> EXPIRED when the clock's date passes effective_end.
    DRAFT agreements never expire. Returns True when it newly expired."""
    if agr["status"] != "ACTIVE":
        return False
    end = datetime.strptime(agr["effective_end"], "%Y-%m-%d").date()
    if get_clock().date() > end:
        agr["status"] = "EXPIRED"
        if persist:
            touch(agr)
        return True
    return False


def descale_overdue(brewer):
    model = db["models"].get(brewer["model_id"])
    if model is None:
        return False
    return (brewer["brew_count"] - brewer["last_descaled_brew_count"]) >= \
        model["descale_interval_brews"]


def eval_brewer_lazy(brewer, persist):
    """Dormancy (>= 60 days since last brew flips ACTIVE -> DORMANT) and
    warranty expiry (clock >= registered_at + warranty_months). Persisted only
    when the observing request is a write."""
    changed = False
    clock = get_clock()
    if brewer["operational"] == "ACTIVE":
        last = parse_dt_val(brewer["last_brew_at"])
        if (clock - last).total_seconds() >= DORMANCY_DAYS * 86400:
            brewer["operational"] = "DORMANT"
            changed = True
    if brewer["warranty_status"] == "IN_WARRANTY":
        model = db["models"].get(brewer["model_id"])
        if model is not None:
            reg = parse_dt_val(brewer["registered_at"])
            if clock >= add_months(reg, model["warranty_months"]):
                brewer["warranty_status"] = "EXPIRED"
                changed = True
    if changed and persist:
        touch(brewer)
    return changed


# ---------------------------------------------------------------- royalties
def bracket_cents(units, start_position, tiers):
    """Shared marginal bracket walk. Brackets are marginal: units up to each
    up_to_units boundary are billed at that bracket's millicents_per_pod; the
    trailing null bracket absorbs the remainder. Each slice is rounded half-up
    to 2 decimal places as it accumulates; the total rounds half-up to cents."""
    if units <= 0:
        return 0
    cents = Decimal("0")
    consumed = start_position
    remaining = units
    for tier in tiers:
        if remaining <= 0:
            break
        cap = tier["up_to_units"]
        room = None if cap is None else max(0, cap - consumed)
        take = remaining if room is None else min(remaining, room)
        if take <= 0:
            continue
        slice_cents = q2(Decimal(take) * Decimal(tier["millicents_per_pod"]) / Decimal(1000))
        cents += slice_cents
        consumed += take
        remaining -= take
    return q0(cents)


def latest_audit(agreement_id):
    audits = [a for a in db["audits"].values() if a["agreement_id"] == agreement_id]
    if not audits:
        return None
    return max(audits, key=lambda a: (a["_audited_dt"], a["created_at"], a["_seq"]))


def compute_final_royalty(stmt, agr):
    """Final variant: bracket position starts at same-year ISSUED|SETTLED
    cumulative sell-through units, then exclusivity -> quality-penalty ->
    unlicensed-discount multipliers, each step re-rounded half-up to cents."""
    year = stmt["period"][:4]
    prior = sum(
        o["sell_through_units"]
        for o in db["statements"].values()
        if o["agreement_id"] == agr["id"]
        and o["id"] != stmt["id"]
        and o["status"] in ("ISSUED", "SETTLED")
        and o["period"][:4] == year
    )
    base = bracket_cents(stmt["sell_through_units"], prior, agr["royalty_tiers"])
    if agr["exclusive"]:
        step1 = q0(Decimal(base) * (Decimal(1) - Decimal(EXCLUSIVITY_DISCOUNT_PCT) / Decimal(100)))
    else:
        step1 = base
    latest = latest_audit(agr["id"])
    if latest is not None and latest["defect_rate_ppm"] > DEFECT_SOFT_MAX_PPM:
        step2 = q0(Decimal(step1) * (Decimal(1) + Decimal(QUALITY_PENALTY_PCT) / Decimal(100)))
    else:
        step2 = step1
    if stmt["unlicensed_share_pct"] >= UNLICENSED_SHARE_THRESHOLD_PCT:
        return q0(Decimal(step2) * (Decimal(1) - Decimal(UNLICENSED_DISCOUNT_PCT) / Decimal(100)))
    return step2


# ---------------------------------------------------------------- varieties
def variety_velocity(variety):
    """Sum of actual_units over COMPLETED runs whose window_end lies inside
    [clock - 90 days, clock], inclusive on both ends."""
    clock = get_clock()
    lo = clock - timedelta(days=90)
    total = 0
    for r in db["runs"].values():
        if r["variety_id"] != variety["id"] or r["status"] != "COMPLETED":
            continue
        we = r["_we"]
        if lo <= we <= clock:
            total += r["actual_units"] or 0
    return total


def is_slow_mover(variety):
    created = parse_dt_val(variety["created_at"])
    age_ok = created <= get_clock() - timedelta(days=SLOW_MOVER_MIN_AGE_DAYS)
    return age_ok and variety_velocity(variety) < SLOW_MOVER_FLOOR_UNITS_90D


# ---------------------------------------------------------------- brewer models
def subsidy_snapshot():
    base = sum(1 for b in db["brewers"].values()
               if b["operational"] in ("ACTIVE", "DORMANT"))
    return min(SUBSIDY_CAP_CENTS, q0(Decimal(base * RECOVERABLE_PER_BREWER_CENTS)))


# ---------------------------------------------------------------- households
def household_metrics(hh):
    """Recompute the four computed household fields against the logical clock."""
    brewers = [b for b in db["brewers"].values() if b["household_id"] == hh["id"]]
    for b in brewers:
        eval_brewer_lazy(b, persist=False)
    active = [b for b in brewers if b["operational"] == "ACTIVE"]
    dormant = [b for b in brewers if b["operational"] == "DORMANT"]
    installed = len(active) + len(dormant)
    if active:
        engagement = "ENGAGED"
    elif dormant:
        engagement = "LAPSED"
    else:
        engagement = "CHURNED"

    recs = sorted(
        (r for r in db["consumption"].values() if r["household_id"] == hh["id"]),
        key=lambda r: r["period"], reverse=True,
    )[:3]
    if not recs:
        trailing = Decimal("0.00")
    else:
        weights = (3, 2, 1)[:len(recs)]
        num = sum(w * r["pods_brewed"] for w, r in zip(weights, recs))
        trailing = q2(Decimal(num) / Decimal(sum(weights)))

    if engagement == "ENGAGED":
        ef = Decimal("1.0")
    elif engagement == "LAPSED":
        ef = Decimal("0.4")
    else:
        ef = Decimal("0.0")
    df = Decimal("0.85") if any(
        b["operational"] == "ACTIVE" and descale_overdue(b) for b in brewers
    ) else Decimal("1.0")
    nondecom = [b for b in brewers if b["operational"] != "DECOMMISSIONED"]
    wf = Decimal("0.90") if (
        installed > 0 and all(b["warranty_status"] != "IN_WARRANTY" for b in nondecom)
    ) else Decimal("1.0")
    expected = q2(Decimal(hh["size"] * PER_PERSON_PODS) * ef * df * wf)

    return {
        "installed_brewers": installed,
        "engagement": engagement,
        "trailing_avg_pods": float(trailing),
        "expected_monthly_pods": float(expected),
    }
