"""Calculation rules (SCAFFOLD Table 3): vote_tally, retail_allocation_waterfall,
ticket_dynamic_price, packing_penalty, licensed_royalty,
recall_severity_classification, session_booked_units, run_production_mass_balance,
spec_boxes_reconciliation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    CHARTER_GROUP_MULT, CLASS_I_FLOOR, CLASS_II_FLOOR, COOLING_I_DAYS,
    COOLING_II_DAYS, COOLING_III_DAYS, GROUP20_MIN_UNITS, GROUP20_MULT,
    GROUP50_MIN_UNITS, GROUP50_MULT, HIGH_MULT, HIGH_TIER_FLOOR,
    INTRO_THRESHOLD, LOW_MULT, LOW_TIER_CEIL, MID_MULT, MIN_TURNOUT,
    OVER_FACTOR, PROJECTED_STAGES, RETIRE_THRESHOLD, SEASON_END, TIER_RANK,
    UNDER_UNIT_PENALTY_CENTS, WEEKEND_MULT,
)
from store import STORE, parse_dt
from validation import touch


# ---------------------------------------------------------------- spec aggregates
def spec_lots(spec_id):
    """Lots of runs created with this spec, FIFO order (created_at, lot_seq)."""
    lots = [lot for lot in STORE.lots.values()
            if STORE.runs[lot["production_run_id"]]["assortment_spec_id"] == spec_id]
    lots.sort(key=lambda lot: (lot["created_at"], lot["lot_seq"]))
    return lots


def spec_boxes_available(spec_id):
    return sum(lot["boxes_on_hand"] for lot in spec_lots(spec_id)
               if lot["status"] in ("AVAILABLE", "DEPLETED"))


def spec_boxes_reserved(spec_id):
    total = 0
    for alloc in STORE.allocations.values():
        if alloc["assortment_spec_id"] != spec_id:
            continue
        if alloc["status"] == "REQUESTED":
            total += alloc["allocated_boxes_provisional"]
        elif alloc["status"] == "COMMITTED":
            total += alloc["allocated_boxes_final"]
    return total


def spec_is_deprecated(spec):
    for entry in spec["entries"]:
        color = STORE.colors.get(entry["color_id"])
        if color is not None and color["status"] in ("RETIRED", "ARCHIVED"):
            return True
    return False


def recompute_spec(spec, bump=True):
    """spec_boxes_reconciliation + derived DEPRECATED status (immediate consistency)."""
    changed = False
    status = "DEPRECATED" if spec_is_deprecated(spec) else "ACTIVE"
    if spec["status"] != status:
        spec["status"] = status
        changed = True
    available = spec_boxes_available(spec["id"])
    if spec["boxes_available"] != available:
        spec["boxes_available"] = available
        changed = True
    reserved = spec_boxes_reserved(spec["id"])
    if spec["boxes_reserved"] != reserved:
        spec["boxes_reserved"] = reserved
        changed = True
    if changed and bump:
        touch(spec)
    return spec


# ------------------------------------------------------------ allocation waterfall
def projected_boxes(spec_id):
    season_end = parse_dt(SEASON_END)
    clock = STORE.clock_dt
    total = 0
    for run in STORE.runs.values():
        if run["assortment_spec_id"] != spec_id:
            continue
        if run["stage"] not in PROJECTED_STAGES:
            continue
        end = parse_dt(run["planned_end_date"])
        if season_end >= end >= clock:
            total += run["planned_boxes"]
    return total


def rerun_waterfall(spec):
    """PROVISIONAL walk over the spec's REQUESTED allocations, in rank order."""
    spec_id = spec["id"]
    pool = spec_boxes_available(spec_id) + projected_boxes(spec_id)
    pending = [a for a in STORE.allocations.values()
               if a["assortment_spec_id"] == spec_id and a["status"] == "REQUESTED"]
    pending.sort(key=lambda a: (TIER_RANK[a["priority_tier"]], a["created_at"], a["request_seq"]))
    for alloc in pending:
        share = min(alloc["requested_boxes"], pool)
        pool -= share
        if alloc["allocated_boxes_provisional"] != share:
            alloc["allocated_boxes_provisional"] = share
            touch(alloc)
    recompute_spec(spec)


# --------------------------------------------------------------------- vote tally
def tally_outcome(campaign):
    """vote_tally: exact-decimal ratio, inclusive threshold, quorum gate."""
    total = campaign["votes_total_weighted"]  # Decimal
    yes = campaign["votes_yes_weighted"]      # Decimal
    ratio = Decimal("0") if total == 0 else yes / total
    threshold = INTRO_THRESHOLD if campaign["kind"] == "INTRODUCTION" else RETIRE_THRESHOLD
    if campaign["turnout_count"] >= MIN_TURNOUT and ratio >= threshold:
        return "PASSED"
    return "FAILED"


# ------------------------------------------------------------------ ticket pricing
def _is_weekend(session):
    return parse_dt(session["session_date"]).date().weekday() >= 5


def ticket_price_cents(session, kind, units, booked_before):
    """ticket_dynamic_price: round_half_up applied once to the unit price."""
    base = Decimal(session["base_price_cents"])
    if session["is_charter"]:
        capacity_mult = Decimal("1.0")
        group_mult = CHARTER_GROUP_MULT if kind == "GROUP" else Decimal("1.0")
    else:
        ratio = Decimal(booked_before) / Decimal(session["capacity_units"])
        if ratio < LOW_TIER_CEIL:
            capacity_mult = LOW_MULT
        elif ratio < HIGH_TIER_FLOOR:
            capacity_mult = MID_MULT
        else:
            capacity_mult = HIGH_MULT
        if kind == "GROUP" and units >= GROUP50_MIN_UNITS:
            group_mult = GROUP50_MULT
        elif kind == "GROUP" and units >= GROUP20_MIN_UNITS:
            group_mult = GROUP20_MULT
        else:
            group_mult = Decimal("1.0")
    day_mult = WEEKEND_MULT if _is_weekend(session) else Decimal("1.0")
    unit = (base * capacity_mult * group_mult * day_mult).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(unit) * units


def session_bounds(session):
    """(start, end) instants: session_date midnight + start_minute / + duration."""
    date = parse_dt(session["session_date"]).date()
    start = datetime(date.year, date.month, date.day,
                     tzinfo=timezone.utc) + timedelta(minutes=session["start_minute"])
    return start, start + timedelta(minutes=session["duration_minutes"])


# ----------------------------------------------------------------- packing penalty
def evaluate_packing(spec, planned_boxes, packed_map):
    """packing_penalty (per-line round_half_up, then sum) + mass balance.

    Returns (packing_variance_units, packing_penalty_cents, boxes_produced, waste).
    """
    variance_total = 0
    penalty_total = 0
    packed_sum = 0
    boxes_produced = None
    for entry in spec["entries"]:
        expected = entry["count"] * planned_boxes
        packed = packed_map[entry["color_id"]]
        variance = abs(packed - expected)
        factor = OVER_FACTOR if packed > expected else Decimal("1.0")
        line = (Decimal(variance) * UNDER_UNIT_PENALTY_CENTS * factor).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        variance_total += variance
        penalty_total += int(line)
        packed_sum += packed
        floor_boxes = packed // entry["count"]
        boxes_produced = floor_boxes if boxes_produced is None else min(boxes_produced, floor_boxes)
    waste = packed_sum - boxes_produced * spec["box_size"]
    return variance_total, penalty_total, boxes_produced, waste


# ---------------------------------------------------------------- licensed royalty
def compute_royalty_cents(line):
    """licensed_royalty: pinned evaluation order; round_half_up at step (5) only."""
    formula = STORE.formulas.get(line["formula_id"])
    if formula is None:
        return 0
    color_id = formula["color_id"]
    spec_ids = set()
    wholesale = {}
    for spec in STORE.specs.values():
        if any(e["color_id"] == color_id for e in spec["entries"]):
            spec_ids.add(spec["id"])
            wholesale[spec["id"]] = spec["wholesale_price_cents"]
    gross = 0
    returns = 0
    for alloc in STORE.allocations.values():
        if alloc["assortment_spec_id"] not in spec_ids:
            continue
        if alloc["status"] not in ("COMMITTED", "FULFILLED", "RELEASED", "SHORTED"):
            continue
        amount = (alloc["allocated_boxes_final"] or 0) * wholesale[alloc["assortment_spec_id"]]
        gross += amount
        if alloc["status"] in ("RELEASED", "SHORTED"):
            returns += amount
    penalties = sum(run["packing_penalty_cents"] for run in STORE.runs.values()
                    if run["assortment_spec_id"] in spec_ids)
    if line["royalty_base"] == "GROSS":
        base = gross
    else:
        base = max(0, gross - returns - penalties)
    rate = Decimal(str(line["royalty_rate"]))
    return int((rate * Decimal(base)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------- recall severity
def classify_severity(affected_units, hazard_class):
    """recall_severity_classification: threshold base class + hazard bump.
    Returns (severity, cooling_days)."""
    if affected_units >= CLASS_I_FLOOR:
        severity = "CLASS_I"
    elif affected_units >= CLASS_II_FLOOR:
        severity = "CLASS_II"
    else:
        severity = "CLASS_III"
    if hazard_class == "RESTRICTED":
        if severity == "CLASS_III":
            severity = "CLASS_II"
        elif severity == "CLASS_II":
            severity = "CLASS_I"
    elif hazard_class == "SENSITIVE" and severity == "CLASS_III":
        severity = "CLASS_II"
    cooling = {
        "CLASS_I": COOLING_I_DAYS,
        "CLASS_II": COOLING_II_DAYS,
        "CLASS_III": COOLING_III_DAYS,
    }[severity]
    return severity, cooling
