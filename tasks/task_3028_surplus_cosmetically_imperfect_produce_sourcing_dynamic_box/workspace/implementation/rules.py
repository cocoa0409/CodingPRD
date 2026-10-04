"""Pure arithmetic and selection helpers for the §1.3 calculation rules.

No store access, no side effects — every function here is a deterministic
function of its arguments so the caller can order the writes.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

import clock
import common

CENT = Decimal("0.01")


def d(value):
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to a whole unit, half away from zero."""
    return int(d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_cents(value):
    """Round a Decimal to two decimal places, half away from zero."""
    return d(value).quantize(CENT, rounding=ROUND_HALF_UP)


def clamp_int(value, low, high):
    return max(low, min(high, value))


# --- display_price_markup (§1.3) -------------------------------------------

def display_price_cents(lot):
    """The per-item displayed price built from the cost basis."""
    quote = primary_quote(lot["id"])
    resolved_grade = "CONVENTIONAL"
    if quote is not None and quote.get("grade_equivalent"):
        resolved_grade = lot["procurement_grade"]
    multiplier = d(common.GRADE_RETAIL_MULTIPLIER[resolved_grade])
    base = round_half_up(d(lot["unit_cost_cents"]) * multiplier)
    floor = round_half_up(
        d(lot["unit_cost_cents"]) * d(common.FLOOR_MULTIPLIER[lot["category"]])
    )
    return max(floor, base)


def primary_quote(lot_id):
    """The lot's deterministic primary ConventionalQuote, or None."""
    cached = _PRIMARY_CACHE["map"].get(lot_id)
    if cached is not None:
        return cached
    if lot_id in _PRIMARY_CACHE["map"]:
        return None
    computed = compute_primary_for(lot_id)
    if computed is None:
        _PRIMARY_CACHE["map"][lot_id] = None
    return computed


_PRIMARY_CACHE = {"map": {}}


def compute_primary_for(lot_id):
    import store

    lot = store.SUPPLY_LOTS.get(lot_id)
    if lot is None:
        return None
    rows = [q for q in store.CONVENTIONAL_QUOTES.values()
            if q["supply_lot_id"] == lot_id]
    if not rows:
        return None
    same_grade = [q for q in rows if q.get("grade_equivalent")]
    pool = same_grade if same_grade else rows
    ordered = sorted(pool, key=lambda r: (r["created_at"], r["_seq"]))
    winner = ordered[0]
    for row in rows:
        row["is_primary"] = row is winner
    _PRIMARY_CACHE["map"][lot_id] = winner
    return winner


def rebuild_primary_quotes():
    """Stamp exactly one deterministic primary quote per lot.

    The primary is the lowest-``created_at`` quote of the lot whose grade is
    equivalent when one exists, otherwise the lowest-``created_at`` quote.
    Identifier never participates, so the same evidence set always resolves to
    the same primary.
    """
    import store

    mapping = {}
    quotes = store.CONVENTIONAL_QUOTES.values()
    lot_ids = {q["supply_lot_id"] for q in quotes}
    for lot_id in lot_ids:
        lot = store.SUPPLY_LOTS.get(lot_id)
        if lot is None:
            continue
        rows = [q for q in quotes if q["supply_lot_id"] == lot_id]
        same_grade = [q for q in rows if q.get("grade_equivalent")]
        pool = same_grade if same_grade else rows
        ordered = sorted(pool, key=lambda r: (r["created_at"], r["_seq"]))
        for row in rows:
            row["is_primary"] = row is ordered[0]
        mapping[lot_id] = ordered[0]
    for lot_id, quote in list(mapping.items()):
        if store.SUPPLY_LOTS.get(lot_id) is None:
            del mapping[lot_id]
    _PRIMARY_CACHE["map"] = mapping
    for lot in store.SUPPLY_LOTS.values():
        lot["source_count"] = source_count_for(lot)
    for quote in quotes:
        quote["source_count"] = source_count_for(
            store.SUPPLY_LOTS.get(quote["supply_lot_id"])
        )


def source_count_for(lot):
    """§2.9: the lot's substantiating sources, capped at three."""
    if lot is None:
        return 0
    import store

    total = sum(1 for q in store.CONVENTIONAL_QUOTES.values()
                if q["supply_lot_id"] == lot["id"])
    return min(total, common.SUBSTANTIATION_MAX_SOURCES)


def grade_equivalent_source_count_for(lot):
    import store

    if lot is None:
        return 0
    return sum(1 for q in store.CONVENTIONAL_QUOTES.values()
               if q["supply_lot_id"] == lot["id"] and q.get("grade_equivalent"))


def substantiation_status_for(lot):
    """§2.9: SUBSTANTIATED only with a same-grade source and <= 3 sources."""
    if lot is None:
        return "UNSUBSTANTIATED"
    import store

    rows = [q for q in store.CONVENTIONAL_QUOTES.values()
            if q["supply_lot_id"] == lot["id"]]
    if not rows:
        return "UNSUBSTANTIATED"
    has_same_grade = any(q.get("grade_equivalent") for q in rows)
    if has_same_grade and len(rows) <= common.SUBSTANTIATION_MAX_SOURCES:
        return "SUBSTANTIATED"
    return "UNSUBSTANTIATED"


# --- billing_weight_apportion (§1.3) ---------------------------------------

def billing_weight_grams(lot):
    return max(lot["unit_weight_grams"],
               common.MIN_BILLING_WEIGHT_GRAMS[lot["category"]])


def line_price_cents(billed_weight, lot_display_price_cents):
    """billed grams * per-item price / 1000, rounded half-up once."""
    return round_half_up(
        d(billed_weight) * d(lot_display_price_cents) / Decimal("1000")
    )


def line_units_cap():
    return common.MAX_LINES_PER_BOX


# --- order_window_plan (§1.3) ----------------------------------------------

def cycle_length_hours(cadence):
    return common.HOURS_PER_CYCLE[cadence]


# §2.4: the logical clock's default reading is the system's service-cycle
# epoch, so a cycle's start instant is a fixed function of its index and of the
# subscription's cadence rather than of when the row happened to be written.
SERVICE_CYCLE_EPOCH = "2026-09-01T00:00:00.000Z"


def start_of_service_cycle(subscription, serving_cycle_index):
    """The instant a service cycle begins."""
    base = clock.parse_instant(SERVICE_CYCLE_EPOCH)
    offset = (serving_cycle_index - 1) * cycle_length_hours(subscription["cadence"])
    return clock.plus_hours(base, offset)


def order_window_plan(subscription, serving_cycle_index, center, created_at_iso):
    start = start_of_service_cycle(subscription, serving_cycle_index)
    lead = common.CUTOFF_LEAD_HOURS[center["region"]]
    ready_deadline = clock.plus_hours(start, -lead)
    build_window = common.BUILD_WINDOW_HOURS
    if center.get("forward_posture") == "DEGRADED":
        build_window *= 2
    build_deadline = clock.plus_hours(start, build_window)
    created_at = clock.parse_instant(created_at_iso)
    return {
        "ready_deadline": clock.format_instant(ready_deadline),
        "build_deadline": clock.format_instant(build_deadline),
        "cutoff_met": created_at < ready_deadline,
    }


def within_build_window(order):
    deadline = clock.parse_instant(order["build_deadline"])
    return clock.now() <= deadline


# --- cold_chain_selection (§1.3) -------------------------------------------

def cold_chain_selection(order, items):
    routed_region = order["routing_region"]
    posture = order.get("_forward_posture", "OPEN")
    lanes = common.LANE_TRANSIT_DAYS[routed_region]
    if posture == "DEGRADED":
        lanes += 1

    cold_weight = sum(i["billed_unit_weight_grams"] for i in items
                      if i["category"] in common.COLD_CHAIN_CATEGORIES)
    other_weight = sum(i["billed_unit_weight_grams"] for i in items
                       if i["category"] not in common.COLD_CHAIN_CATEGORIES)
    if other_weight == 0:
        cold_weight += common.COLD_PACKAGING_ALLOWANCE_GRAMS

    required = cold_weight >= common.COLD_WEIGHT_REQUIRED_GRAMS
    insulated = (routed_region in common.WARM_LANE_REGIONS
                 and lanes >= common.INSULATED_TRANSIT_MIN_DAYS)

    if not required:
        grade, coolant, status = "LIGHT", 0, "NOT_REQUIRED"
    elif insulated:
        if lanes >= 4:
            grade = "HEAVY"
        else:
            grade = "MEDIUM"
        coolant = int(math.ceil(
            Decimal(cold_weight) / Decimal(common.COOLANT_UNIT_DIVISOR)))
    else:
        grade, coolant = "MEDIUM", 2
        status = "SELECTED"
    if required:
        status = "SELECTED"
    if posture == "DEGRADED":
        coolant = coolant * 2
    return {
        "cold_item_weight_grams": cold_weight,
        "lane_transit_days": lanes,
        "insulation_grade": grade,
        "coolant_units": coolant,
        "selection_status": status,
    }


# --- cap_quality_credit (§1.3) ---------------------------------------------

def cap_quality_credit(claim, item, lot):
    """The smallest of the three ceilings, per §3.3.

    The 75 percent line cap is the only ceiling that can land off a whole cent,
    so it is rounded half-up before the min chain; the issued value is a
    whole-cent integer, as §2.5 requires of every monetary figure.
    """
    unit_credit = d(common.FLAT_UNIT_CREDIT_CENTS[claim["reason_code"]]) \
        * d(item["units"]) * d(common.GRADE_MULTIPLIER[lot["procurement_grade"]])
    line_cap = d(round_half_up(d("0.75") * d(item["line_price_cents"])))
    requested = d(claim["requested_credit_cents"])
    grace = min(requested, d(common.PER_CLAIM_GRACE_CENTS))
    grace_ceiling = requested + grace
    issued = min(unit_credit, line_cap, grace_ceiling)
    return round_half_up(issued)


# --- reliability_score (§1.3) ----------------------------------------------

def reliability_score_bp(supplier):
    awarded = supplier["lots_awarded_total"]
    accepted = supplier["lots_accepted_total"]
    on_time = supplier["lots_on_time_total"]
    upheld = supplier["claims_upheld_total"]

    if awarded == 0:
        on_time_bp = 10000
        acceptance_bp = 10000
    else:
        on_time_bp = round_half_up(d(10000) * d(on_time) / d(awarded))
        acceptance_bp = round_half_up(d(10000) * d(accepted) / d(awarded))
    if accepted == 0:
        quality_bp = 10000
    else:
        quality_bp = round_half_up(d(10000) * d(accepted - upheld) / d(accepted))

    score = (d("0.40") * d(on_time_bp) + d("0.40") * d(acceptance_bp)
             + d("0.20") * d(quality_bp))
    return round_half_up(score)


def relationship_status_for(score):
    if score >= common.PREFERRED_FLOOR_BP:
        return "PREFERRED"
    if score >= common.STANDARD_FLOOR_BP:
        return "STANDARD"
    if score >= common.ON_WATCH_FLOOR_BP:
        return "ON_WATCH"
    return "SUSPENDED"


# --- regional_center_assignment (§1.3 / §2.6) -------------------------------

def regional_center_assignment(service_region):
    """Active centers of the region, ranked by code ascending; winner is first."""
    import store

    candidates = [c for c in store.FULFILLMENT_CENTERS.values()
                  if c.get("is_active") and c["region"] == service_region]
    if not candidates:
        return None
    return sorted(candidates, key=lambda c: c["code"])[0]


# --- allocate_box_lines §2.8 caps ------------------------------------------

def class_caps():
    cap_preference = math.ceil(d(common.PREFERENCE_RATIO) * common.BOX_UNIT_TARGET)
    cap_filler = math.ceil(d(common.FILLER_RATIO) * common.BOX_UNIT_TARGET)
    cap_specialty = common.BOX_UNIT_TARGET - cap_preference - cap_filler
    return cap_preference, cap_filler, cap_specialty


def preference_tag_specificity(lot):
    return len(lot.get("preference_tags") or [])


def rank_lots(lots):
    """§2.8 selector ordering."""
    return sorted(lots, key=lambda l: (
        -preference_tag_specificity(l),
        -l["shelf_life_days"],
        l["unit_cost_cents"],
        l["created_at"],
        l["_seq"],
    ))