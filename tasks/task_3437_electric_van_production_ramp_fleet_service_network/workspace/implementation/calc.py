"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 2.10 and 3).

All precision-sensitive arithmetic uses Decimal; rounding is ROUND_HALF_UP
exactly where each calculation specifies it.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from errors import ApiError
import errors as E
import store
from store import DB


def D(v):
    return Decimal(str(v))


# ------------------------------------------------------- platform constants

FRANCHISE_BLOCKED_STATES = {"TX", "MI", "WV"}
MAX_DEPOT_CREW = 4
VAN_TRAVEL_BUFFER_MINUTES = 45
MODULE_MAX_FAILURES = 2


# ------------------------------------------- supplier_readiness_scoring

TIER_A_ON_TIME_PCT = D("95.0")
TIER_A_YIELD_PCT = D("98.0")
TIER_B_ON_TIME_PCT = D("85.0")
TIER_B_YIELD_PCT = D("92.0")
TIER_B_MAX_CORRECTIVE = 2


def supplier_tier(on_time_pct, first_pass_yield_pct, open_corrective_actions):
    """Conjunctive tiers checked A first, then B, else C; boundaries inclusive."""
    ot = D(on_time_pct)
    y = D(first_pass_yield_pct)
    ca = open_corrective_actions
    if ot >= TIER_A_ON_TIME_PCT and y >= TIER_A_YIELD_PCT and ca == 0:
        return "A"
    if ot >= TIER_B_ON_TIME_PCT and y >= TIER_B_YIELD_PCT and ca <= TIER_B_MAX_CORRECTIVE:
        return "B"
    return "C"


# ------------------------------------------- production_capacity_gate

RAMP_BASE_WEEKLY_UNITS = 8
TIER_WEEKLY_UNITS = {"A": 24, "B": 10, "C": 0, "UNAUDITED": 0}


def _iso_week_start(dt):
    d = dt.date() - timedelta(days=dt.weekday())
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def ramp_has_capacity():
    """Allow a VIN registration iff this ISO week's count is strictly below capacity."""
    capacity = RAMP_BASE_WEEKLY_UNITS + sum(
        TIER_WEEKLY_UNITS.get(s["readiness_tier"], 0) for s in DB.suppliers.values())
    wstart = _iso_week_start(store.now())
    wend = wstart + timedelta(days=7)
    count = sum(1 for v in DB.vehicles.values()
                if wstart <= v["_created_dt"] < wend)
    return count < capacity


# ------------------------------------------- depot_capacity_allocation

IN_FLIGHT_STATES = ("SURVEY", "UTILITY_REVIEW", "PERMITTING", "INSTALLATION")


def committed_kw(depot_id):
    """Pinned evaluation order step (1): in-flight requested + commissioned kW."""
    total = D(0)
    for p in DB.charging_projects.values():
        if p["depot_id"] != depot_id:
            continue
        if p["status"] in IN_FLIGHT_STATES:
            total += D(p["requested_capacity_kw"])
        elif p["status"] == "COMMISSIONED":
            total += D(p["commissioned_capacity_kw"])
    return total


def headroom_ok(depot, requested_capacity_kw):
    """Step (3): requested <= total - committed (inclusive boundary)."""
    headroom = D(depot["total_capacity_kw"]) - committed_kw(depot["id"])
    return D(requested_capacity_kw) <= headroom


def crew_window_conflict(depot_id, cand_start, cand_end, cand_crew):
    """Aggregate crew rule: any pointwise-overlapping set of projects at the depot
    in {PERMITTING, INSTALLATION} plus the candidate must sum to <= MAX_DEPOT_CREW.
    Windows are inclusive closed bounds."""
    rows = [
        (p["_w_start"], p["_w_end"], p["crew_count"])
        for p in DB.charging_projects.values()
        if p["depot_id"] == depot_id and p["status"] in ("PERMITTING", "INSTALLATION")
    ]
    rows.append((cand_start, cand_end, cand_crew))
    points = []
    for s, e, _ in rows:
        points.append(s)
        points.append(e)
    for t in points:
        covering = sum(c for s, e, c in rows if s <= t <= e)
        if covering > MAX_DEPOT_CREW:
            return True
    return False


# ------------------------------------------- charging_demand_gate

PER_VEHICLE_DRAW_KW = D("19.2")
UTILIZATION_FACTOR = D("0.8")


def charging_gate_pass(depot_id):
    """commissioned kW * 0.8 >= (in-service vehicles at depot + 1) * 19.2."""
    commissioned = D(0)
    for p in DB.charging_projects.values():
        if p["depot_id"] == depot_id and p["status"] == "COMMISSIONED":
            commissioned += D(p["commissioned_capacity_kw"])
    in_service = 0
    for v in DB.vehicles.values():
        if v["delivery_status"] != "COMMISSIONED":
            continue
        order = DB.orders.get(v["vehicle_order_id"])
        if order is not None and order["depot_id"] == depot_id:
            in_service += 1
    required = D(in_service + 1) * PER_VEHICLE_DRAW_KW
    return commissioned * UTILIZATION_FACTOR >= required


# ------------------------------------------- battery_eol_valuation

SOH_EOL_THRESHOLD = D("70.0")
PACK_BASE_VALUE_CENTS = D(1800000)
RECOVERY_RATE_PER_KWH_CENTS = D(12000)


def eol_valuations(soh, pack_kwh):
    """Return (refurbish_cents, recovery_cents), both round_half_up integers."""
    s = D(soh)
    if s >= D("90"):
        mult = D("0.85")
    elif s >= D("80"):
        mult = D("0.70")
    elif s >= D("70"):
        mult = D("0.55")
    else:
        mult = D("0.35")
    refurbish = (PACK_BASE_VALUE_CENTS * mult).quantize(D("1"), rounding=ROUND_HALF_UP)
    recovery = (D(pack_kwh) * RECOVERY_RATE_PER_KWH_CENTS * s / D(100)).quantize(
        D("1"), rounding=ROUND_HALF_UP)
    return int(refurbish), int(recovery)


# ------------------------------------------- warranty_settlement

LABOR_RATE_CENTS_PER_HOUR = D(17500)
DEDUCTIBLE_CENTS = 25000
COVERAGE_PCT = {
    "BATTERY": D("1.0"),
    "POWERTRAIN": D("1.0"),
    "CHARGING": D("0.9"),
    "BODY": D("0.8"),
}


def warranty_settlement(claim_lines):
    """Pinned nested rounding: each component of each line rounded to integer
    cents first, lines summed, then the single per-claim deductible subtracted."""
    total = 0
    for line in claim_lines:
        cov = COVERAGE_PCT[line["component_class"]]
        part = (D(line["part_cost_cents"]) * cov).quantize(D("1"), rounding=ROUND_HALF_UP)
        labor = (D(line["labor_hours"]) * LABOR_RATE_CENTS_PER_HOUR * cov).quantize(
            D("1"), rounding=ROUND_HALF_UP)
        total += int(part) + int(labor)
    return max(0, total - DEDUCTIBLE_CENTS)


# ------------------------------------------- campaign_rollout_gate

CANARY_MIN_COHORT = 3
EXPANDED_MIN_COHORT = 10
ROLLOUT_SUCCESS_RATE_MIN = Fraction(19, 20)  # 0.95, compared exactly


def check_rollout_gate(campaign, min_cohort):
    cohort = campaign["succeeded_count"] + campaign["failed_count"]
    if cohort == 0:
        raise ApiError(E.ERR_EMPTY_COHORT, 409,
                       "stage advance requires at least one recorded result")
    if cohort < min_cohort:
        raise ApiError(E.ERR_ROLLOUT_GATE_FAILED, 409,
                       "cohort size %d below minimum %d" % (cohort, min_cohort))
    rate = Fraction(campaign["succeeded_count"], cohort)
    if rate < ROLLOUT_SUCCESS_RATE_MIN:
        raise ApiError(E.ERR_ROLLOUT_GATE_FAILED, 409,
                       "success rate below 0.95")


# ------------------------------------------- delivery_promise_calculation

PROMISE_BASE_DAYS = 28
PROMISE_PER_TEN_VANS_DAYS = 7
SUPPLY_RISK_PUSH_DAYS = 14


def promise_date(confirm_dt, quantity):
    days = PROMISE_BASE_DAYS + PROMISE_PER_TEN_VANS_DAYS * math.ceil(quantity / 10)
    return (confirm_dt.date() + timedelta(days=days)).isoformat()


def push_promise_date(date_str, days):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (d + timedelta(days=days)).isoformat()


# ------------------------------------------- uptime_credit

CREDIT_CAP_PCT = D("30.0")

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_month(s):
    """Parse a YYYY-MM string into (year, month); None when malformed."""
    if not isinstance(s, str) or not _MONTH_RE.match(s):
        return None
    y, m = int(s[:4]), int(s[5:7])
    if not (1 <= m <= 12):
        return None
    return (y, m)


def _month_bounds(y, m):
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end, (end - start).days


def in_service_fleet(contract):
    """Vehicles of the contract's customer at AT_DEPOT or COMMISSIONED."""
    out = []
    for v in DB.vehicles.values():
        if v["delivery_status"] not in ("AT_DEPOT", "COMMISSIONED"):
            continue
        order = DB.orders.get(v["vehicle_order_id"])
        if order is not None and order["fleet_customer_id"] == contract["fleet_customer_id"]:
            out.append(v)
    return out


def close_month_credit(contract, month):
    """Return (uptime_pct Decimal at 1dp, credit_cents int)."""
    y, m = parse_month(month)
    mstart, mend, days_in_month = _month_bounds(y, m)
    fleet = in_service_fleet(contract)
    n = len(fleet)
    if n == 0:
        raise ApiError(E.ERR_INVALID_STATE, 409, "no in-service fleet to measure")
    fleet_ids = {v["id"] for v in fleet}

    def overlap(ev):
        s = max(ev["start"], mstart)
        e = min(ev["end"] if ev["end"] is not None else mend, mend)
        return (s, e) if s < e else None

    if contract["pro_rating"] == "ROUTE_DAY":
        downtime_days = D(0)
        for v in fleet:
            days = set()
            for ev in contract["_events_parsed"]:
                if ev["vehicle_id"] != v["id"]:
                    continue
                ov = overlap(ev)
                if ov is None:
                    continue
                s, e = ov
                d = s.date()
                last = (e - timedelta(microseconds=1)).date()
                while d <= last:
                    days.add(d)
                    d += timedelta(days=1)
            downtime_days += D(len(days))
    else:  # VEHICLE_HOUR: per-event overlap rounded to 0.1h before summation
        total_hours = D(0)
        for ev in contract["_events_parsed"]:
            if ev["vehicle_id"] not in fleet_ids:
                continue
            ov = overlap(ev)
            if ov is None:
                continue
            s, e = ov
            hours = D(str((e - s).total_seconds())) / D(3600)
            total_hours += hours.quantize(D("0.1"), rounding=ROUND_HALF_UP)
        downtime_days = total_hours / D(24)

    uptime = ((D(1) - downtime_days / (D(n) * D(days_in_month))) * D(100)).quantize(
        D("0.1"), rounding=ROUND_HALF_UP)
    shortfall = max(D(0), D(contract["committed_uptime_pct"]) - uptime)
    credit_pct = (
        min(shortfall, D("2.0")) * D(2)
        + min(max(shortfall - D("2.0"), D(0)), D("3.0")) * D(5)
        + max(shortfall - D("5.0"), D(0)) * D(10)
    )
    credit_pct = min(credit_pct, CREDIT_CAP_PCT)
    credit = (D(contract["monthly_service_fee_cents"]) * credit_pct / D(100)).quantize(
        D("1"), rounding=ROUND_HALF_UP)
    return uptime, int(credit)
