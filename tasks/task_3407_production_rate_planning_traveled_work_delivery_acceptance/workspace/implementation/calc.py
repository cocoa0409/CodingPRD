"""Calculations (SCAFFOLD `calculations`; PRD sections 2.6, 2.9, 3.2-3.9).

Every constant is pinned to PRD prose:
- GATING_THRESHOLD_INDEX 85.0              (PRD 2.9 / 3.2: readiness index gating bar)
- DISTRESS_INDEX_FLOOR 60.0                (PRD 2.9: DISTRESSED below 60.0)
- DISTRESS_OPEN_ESCAPE_COUNT 3             (PRD 2.9: DISTRESSED at >= 3 open escapes)
- BURDEN_PENALTY_PER_OPEN_HOUR 0.5         (PRD 2.9: half a point per open traveled hour)
- MAX_BURDEN_PENALTY 20.0                  (PRD 2.9: burden capped at 20.0 points)
- PROVISIONAL_RATE_CENTS 15000             (PRD 3.5: provisional variant hourly rate)
- ACTUAL_RATE_CENTS 17500                  (PRD 3.5: final variant hourly rate)
- SNAG_HOURS_EACH 4                        (PRD 3.5/3.8: four hours per walkthrough snag)
- source multipliers 1.0 / 1.5 / 1.25 / 1.0 (PRD 3.5)
- LD_DAILY_CENTS 250000, LD_CAP_PCT 0.10   (PRD 3.9: contractual liquidated damages)
- GOODWILL_BASE_CENTS 1000000, GOODWILL_DAILY_CENTS 100000 (PRD 3.9)
- VOLUME_DISCOUNT_FACTOR 0.95              (PRD 3.7: five-percent volume discount)
- CANCELLATION_PENALTY_PCT 0.30            (PRD 3.3: thirty percent cancellation penalty)
- MAX_NEGOTIATION_ROUNDS 6                 (PRD 3.9: at most six rounds)
- BAY_BUFFER_DAYS 2                        (PRD 3.7: two-day turnaround buffer)
- REGULATOR_NOTIFY_HOURS 24                (PRD 3.6: created_at + 24 hours)
"""
from datetime import timedelta
from decimal import Decimal

from core import D, db, rhu, rhu2, rhu_int

# --- gating_readiness_index (PRD 2.9) ---
GATING_THRESHOLD_INDEX = D("85.0")
DISTRESS_INDEX_FLOOR = D("60.0")
STABLE_INDEX_FLOOR = D("85.0")
DISTRESS_OPEN_ESCAPE_COUNT = 3
BURDEN_PENALTY_PER_OPEN_HOUR = D("0.5")
MAX_BURDEN_PENALTY = D("20.0")

# --- traveled_work_cost (PRD 3.5) ---
PROVISIONAL_RATE_CENTS = 15000
ACTUAL_RATE_CENTS = 17500
SNAG_HOURS_EACH = 4
SOURCE_MULTIPLIERS = {
    "TRAVELED_WORK": D("1.0"),
    "QUALITY_ESCAPE": D("1.5"),
    "FLIGHT_TEST_FAILURE": D("1.25"),
    "WALKTHROUGH_SNAG": D("1.0"),
}
REWORK_SOURCES = tuple(SOURCE_MULTIPLIERS.keys())

# --- delay_compensation (PRD 3.9) ---
LD_DAILY_CENTS = 250000
LD_CAP_PCT = D("0.10")
GOODWILL_BASE_CENTS = 1000000
GOODWILL_DAILY_CENTS = 100000
MAX_NEGOTIATION_ROUNDS = 6

# --- storage_preservation_fee (PRD 3.7) ---
VOLUME_DISCOUNT_FACTOR = D("0.95")
BAY_BUFFER_DAYS = 2

# --- cancellation_reserve (PRD 3.3) ---
CANCELLATION_PENALTY_PCT = D("0.30")

# --- quality escapes (PRD 3.6) ---
REGULATOR_NOTIFY_HOURS = 24

OPEN_ESCAPE_STATES = ("OPEN", "ROOT_CAUSE", "DISPOSITIONED")
SUPPLY_COUNTED_STATES = ("CONFIRMED", "ORDERED", "AT_RISK")


# ---------------------------------------------------------------------------
# Program-scoped entity views
# ---------------------------------------------------------------------------
def program_aircraft(program_id):
    return [a for a in db.aircraft.values() if a["program_id"] == program_id]


def program_aircraft_ids(program_id):
    return {a["id"] for a in program_aircraft(program_id)}


def program_commitments(program_id):
    return [c for c in db.commitments.values() if c["program_id"] == program_id]


def program_workforce_plans(program_id):
    return [w for w in db.workforce_plans.values() if w["program_id"] == program_id]


def program_escapes(program_id):
    ids = program_aircraft_ids(program_id)
    return [e for e in db.escapes.values() if e["aircraft_id"] in ids]


def program_rework_orders(program_id):
    ids = program_aircraft_ids(program_id)
    return [r for r in db.rework_orders.values() if r["aircraft_id"] in ids]


def program_storages(program_id):
    ids = program_aircraft_ids(program_id)
    return [s for s in db.storages.values() if s["aircraft_id"] in ids]


# ---------------------------------------------------------------------------
# Live counters (PRD 2.9)
# ---------------------------------------------------------------------------
def open_escape_count(program_id):
    return sum(1 for e in program_escapes(program_id) if e["status"] in OPEN_ESCAPE_STATES)


def has_critical_open_escape(program_id):
    return any(
        e["severity"] == "CRITICAL" and e["status"] in OPEN_ESCAPE_STATES
        for e in program_escapes(program_id)
    )


def traveled_work_open_hours(program_id):
    """Sum of traveled_hours over TRAVELED packages whose linked TRAVELED_WORK
    rework order is neither CLOSED nor CREDITED (PRD 2.9)."""
    ids = program_aircraft_ids(program_id)
    total = 0
    for wp in db.work_packages.values():
        if wp["aircraft_id"] not in ids or wp["status"] != "TRAVELED":
            continue
        linked = [
            ro
            for ro in db.rework_orders.values()
            if ro["work_package_id"] == wp["id"] and ro["source"] == "TRAVELED_WORK"
        ]
        if any(ro["status"] in ("CLOSED", "CREDITED") for ro in linked):
            continue
        total += wp["traveled_hours"] or 0
    return total


def undelivered_inventory_count(program_id):
    return sum(
        1
        for a in program_aircraft(program_id)
        if a["production_status"] in ("ASSEMBLY_COMPLETE", "IN_STORAGE")
    )


def rework_budget_consumed(program_id):
    """Sum of actual_cost_cents over CLOSED rework orders only (PRD 2.9)."""
    return sum(
        ro["actual_cost_cents"] or 0
        for ro in program_rework_orders(program_id)
        if ro["status"] == "CLOSED"
    )


def aircraft_rework_total(aircraft_id):
    return sum(
        ro["actual_cost_cents"] or 0
        for ro in db.rework_orders.values()
        if ro["aircraft_id"] == aircraft_id and ro["status"] == "CLOSED"
    )


def announced_target_rate(program):
    """proposed_rate of the latest case in ANNOUNCED/GATED_REVIEW (created_at ASC,
    latest wins); falls back to current_rate_per_month (PRD 3.2)."""
    live = [
        rc
        for rc in db.rate_cases.values()
        if rc["program_id"] == program["id"] and rc["status"] in ("ANNOUNCED", "GATED_REVIEW")
    ]
    if not live:
        return program["current_rate_per_month"]
    live.sort(key=lambda rc: (rc["created_at"], rc["_seq"]))
    return live[-1]["proposed_rate"]


# ---------------------------------------------------------------------------
# gating_readiness_index (PRD 2.9); live variant vs current rate, snapshot
# variant vs proposed rate. Percentages carried to exactly two decimals.
# ---------------------------------------------------------------------------
def supply_pct(program, target_rate):
    required = program["required_component_codes"]
    if required == 0:
        return D("100")
    covered = set()
    for c in program_commitments(program["id"]):
        if c["status"] in SUPPLY_COUNTED_STATES and c["committed_rate_per_month"] >= target_rate:
            covered.add(c["component_code"])
    raw = D(100 * len(covered)) / D(required)
    return rhu2(min(D("100"), raw))


def workforce_pct(program):
    plans = program_workforce_plans(program["id"])
    required = sum(w["required_headcount"] for w in plans)
    if not plans or required == 0:
        return D("100")
    hired = sum(w["hired_headcount"] for w in plans)
    raw = D(100 * hired) / D(required)
    return rhu2(min(D("100"), raw))


def burden_penalty(program):
    return min(MAX_BURDEN_PENALTY, BURDEN_PENALTY_PER_OPEN_HOUR * traveled_work_open_hours(program["id"]))


def readiness_index(program, target_rate):
    supply = supply_pct(program, target_rate)
    workforce = workforce_pct(program)
    return rhu2(min(supply, workforce) - burden_penalty(program))


def gating_verdict(program, target_rate):
    index = readiness_index(program, target_rate)
    if index >= GATING_THRESHOLD_INDEX and open_escape_count(program["id"]) == 0:
        return "PASS"
    return "FAIL"


def posture(program):
    """posture_derivation (PRD 2.9): thresholds compared at 2-decimal precision."""
    index = readiness_index(program, program["current_rate_per_month"])
    oec = open_escape_count(program["id"])
    at_risk = any(
        c["status"] == "AT_RISK" for c in program_commitments(program["id"])
    )
    if (
        index < DISTRESS_INDEX_FLOOR
        or has_critical_open_escape(program["id"])
        or oec >= DISTRESS_OPEN_ESCAPE_COUNT
        or at_risk
    ):
        return "DISTRESSED"
    if index >= STABLE_INDEX_FLOOR and oec == 0:
        return "STABLE"
    return "STABILIZING"


# ---------------------------------------------------------------------------
# cancellation_reserve (PRD 3.3): rounded per commitment BEFORE the sum.
# ---------------------------------------------------------------------------
def cancellation_reserve(program_id):
    total = 0
    for c in program_commitments(program_id):
        if c["status"] == "AT_RISK":
            active = c["ordered_quantity"] - c["cancelled_quantity"]
            total += rhu_int(CANCELLATION_PENALTY_PCT * active * c["unit_price_cents"])
        elif c["status"] == "CANCELLED":
            total += c["cancellation_penalty_cents"]
    return total


def cancellation_penalty(cancel_quantity, unit_price_cents):
    return rhu_int(CANCELLATION_PENALTY_PCT * cancel_quantity * unit_price_cents)


# ---------------------------------------------------------------------------
# storage_preservation_fee (PRD 3.7): per-aircraft rounding BEFORE the sum.
# ---------------------------------------------------------------------------
def storage_fees(program_id):
    total = 0
    for sp in program_storages(program_id):
        if sp["status"] != "ACTIVE":
            continue
        days = int((db.clock - sp["window_start"]).total_seconds() // 86400)
        days = max(0, days)
        total += rhu_int(days * sp["daily_rate_cents"] * VOLUME_DISCOUNT_FACTOR)
    return total


def next_preservation_due(sp):
    return sp["last_preserved_at"] + timedelta(days=sp["preservation_cycle_days"])


def is_overdue(sp):
    return sp["status"] == "ACTIVE" and db.clock > next_preservation_due(sp)


# ---------------------------------------------------------------------------
# traveled_work_cost (PRD 3.5)
# ---------------------------------------------------------------------------
def provisional_cost(hours_basis, source):
    return rhu_int(D(hours_basis) * PROVISIONAL_RATE_CENTS * SOURCE_MULTIPLIERS[source])


def final_cost(actual_hours, parts_cents):
    return rhu_int(D(actual_hours) * ACTUAL_RATE_CENTS + D(parts_cents))


# ---------------------------------------------------------------------------
# delay_compensation (PRD 3.9)
# ---------------------------------------------------------------------------
def delay_days(proposed_date, contracted_date):
    return max(0, (proposed_date - contracted_date).days)


def compensation(variant, days_late, contract_price_cents):
    if variant == "GOODWILL":
        return GOODWILL_BASE_CENTS + days_late * GOODWILL_DAILY_CENTS
    per_diem = days_late * LD_DAILY_CENTS
    cap = rhu_int(LD_CAP_PCT * contract_price_cents)
    return min(per_diem, cap)


# ---------------------------------------------------------------------------
# Quality escapes (PRD 3.6)
# ---------------------------------------------------------------------------
def is_late_notification(escape):
    stamp = escape["regulator_notified_at"]
    if stamp is None:
        return False
    return stamp > escape["created_at"] + timedelta(hours=REGULATOR_NOTIFY_HOURS)


# ---------------------------------------------------------------------------
# Workforce plans (PRD 3.1)
# ---------------------------------------------------------------------------
def readiness_ratio(plan):
    if plan["required_headcount"] == 0:
        return D("0")
    return rhu2(D(plan["hired_headcount"]) / D(plan["required_headcount"]))


# ---------------------------------------------------------------------------
# Full live computed block for GET /api/programs/{id} (PRD 2.9)
# ---------------------------------------------------------------------------
def program_computed(program):
    pid = program["id"]
    supply = supply_pct(program, program["current_rate_per_month"])
    workforce = workforce_pct(program)
    burden = burden_penalty(program)
    index = rhu2(min(supply, workforce) - burden)
    oec = open_escape_count(pid)
    at_risk = any(c["status"] == "AT_RISK" for c in program_commitments(pid))
    if (
        index < DISTRESS_INDEX_FLOOR
        or has_critical_open_escape(pid)
        or oec >= DISTRESS_OPEN_ESCAPE_COUNT
        or at_risk
    ):
        posture_value = "DISTRESSED"
    elif index >= STABLE_INDEX_FLOOR and oec == 0:
        posture_value = "STABLE"
    else:
        posture_value = "STABILIZING"
    return {
        "announced_target_rate": announced_target_rate(program),
        "rework_budget_consumed_cents": rework_budget_consumed(pid),
        "cancellation_reserve_cents": cancellation_reserve(pid),
        "supply_chain_readiness_pct": supply,
        "workforce_readiness_pct": workforce,
        "traveled_work_open_hours": traveled_work_open_hours(pid),
        "open_escape_count": oec,
        "readiness_index": index,
        "posture": posture_value,
        "storage_fees_accrued_cents": storage_fees(pid),
        "undelivered_inventory_count": undelivered_inventory_count(pid),
    }
