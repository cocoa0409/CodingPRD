"""Deterministic arithmetic (PRD 2.6, 3.3, 3.4, 3.5, 3.7, 3.8).

Every figure in this module is derived: nothing here reads the wall clock and
nothing rounds later than the step the PRD nominates.
"""

from decimal import Decimal

from store import db
from util import add_hours, add_minutes, ceil_int, cents, dec, floor_int, q2, q4

# PRD 3.1 -- method labor factors.
METHOD_LABOR_FACTOR = {
    "SCRATCH": Decimal("1"),
    "PAR_BAKED": Decimal("0.6"),
    "THAW_AND_SERVE": Decimal("0.25"),
}

# PRD 3.2 -- day-of-week forecast uplift.
DOW_UPLIFT = {
    "MON": Decimal("1"),
    "TUE": Decimal("1"),
    "WED": Decimal("1"),
    "THU": Decimal("1.05"),
    "FRI": Decimal("1.15"),
    "SAT": Decimal("1.25"),
    "SUN": Decimal("1.10"),
}

DAYPART_RANK = {"MORNING": 0, "MIDDAY": 1, "EVENING": 2}
DAYPART_OFFSET_HOURS = {"MORNING": 0, "MIDDAY": 5, "EVENING": 10}

# PRD 3.7 -- decoration effort per tier and lead-time base minutes.
DECORATION_UNITS_PER_TIER = {"SIMPLE": 2, "STANDARD": 4, "PREMIUM": 7}
DECORATION_LEAD_BASE_MINUTES = {"SIMPLE": 60, "STANDARD": 120, "PREMIUM": 240}
DECORATION_UNIT_CENTS = 450


# ---------------------------------------------------------------------------
# labor
# ---------------------------------------------------------------------------

def per_rack_labor(product):
    """base_labor_minutes_per_rack * method factor (unrounded)."""
    return dec(product["base_labor_minutes_per_rack"]) * METHOD_LABOR_FACTOR[product["production_method"]]


def planned_labor_minutes(product, rack_count):
    """PRD 3.4: setup + rack_count * base * factor, half-up to 2dp."""
    return q2(dec(product["setup_labor_minutes"]) + dec(rack_count) * per_rack_labor(product))


def deck_predecessor(run):
    """PRD 3.5: latest COMPLETED run on the same oven+deck finishing at or
    before this run's bake_start_utc, ordered by bake_end_utc desc then
    created_at desc."""
    if not run.get("oven_id") or run.get("bake_start_utc") is None:
        return None
    candidates = []
    for other in db.runs.values():
        if other["id"] == run["id"]:
            continue
        if other.get("oven_id") != run["oven_id"]:
            continue
        if other.get("deck_index") != run["deck_index"]:
            continue
        if other["execution_status"] != "COMPLETED":
            continue
        if other.get("bake_end_utc") is None:
            continue
        if other["bake_end_utc"] <= run["bake_start_utc"]:
            candidates.append(other)
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row["bake_end_utc"], row["_seq"]), reverse=True)
    return candidates[0]


def changeover_allowance(run, product):
    """PRD 3.5: half the oven's changeover buffer when the deck predecessor's
    product carries a different allergen set."""
    predecessor = deck_predecessor(run)
    if predecessor is None:
        return q2(0)
    previous_product = db.products.get(predecessor["product_id"])
    if previous_product is None:
        return q2(0)
    if set(previous_product["allergen_tags"]) == set(product["allergen_tags"]):
        return q2(0)
    oven = db.ovens.get(run["oven_id"])
    buffer_minutes = dec(oven["changeover_buffer_minutes"]) if oven else dec(0)
    return q2(buffer_minutes * Decimal("0.5"))


def final_labor_minutes(run, product, actual_labor):
    raw = dec(actual_labor) if actual_labor is not None else dec(run["planned_labor_minutes"])
    return q2(raw + changeover_allowance(run, product))


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------

def run_ingredient_cost_cents(product, rack_count):
    """PRD 3.4: per-line half-up rounding, then the sum of rounded lines."""
    total = 0
    for line in product["recipe_lines"]:
        ingredient = db.ingredients.get(line["ingredient_id"])
        if ingredient is None:
            continue
        total += cents(dec(rack_count) * dec(line["units_per_rack"]) * dec(ingredient["unit_cost_cents"]))
    return total


def unit_cost_basis_cents(ingredient_cost, actual_units):
    """PRD 3.5: divide then round half up to whole cents, once."""
    if not actual_units:
        return 0
    return cents(dec(ingredient_cost) / dec(actual_units))


def waste_cost_cents(unit_basis, units):
    """PRD 3.6: multiply the already-rounded basis; no further rounding."""
    return int(unit_basis) * int(units)


def markdown_unit_price_cents(product):
    return cents(dec(product["unit_retail_cents"]) * (Decimal("1") - dec(product["markdown_pct"])))


# ---------------------------------------------------------------------------
# run timing
# ---------------------------------------------------------------------------

def run_timings(product, proof_start, bake_start):
    """(bake_end_utc, ready_utc, expires_utc) for a run being created."""
    if product["production_method"] == "THAW_AND_SERVE":
        bake_end = None
        ready = db.now()
    else:
        bake_end = add_minutes(bake_start, product["bake_minutes"])
        ready = add_minutes(bake_end, product["cool_minutes"])
    expires = add_hours(ready, product["shelf_life_hours"])
    return bake_end, ready, expires


# ---------------------------------------------------------------------------
# oven deck occupation (PRD 3.4)
# ---------------------------------------------------------------------------

def bake_interval(run, product):
    start = run.get("bake_start_utc")
    if start is None:
        return None
    return start, add_minutes(start, product["bake_minutes"])


def deck_collides(oven, deck_index, start, end, exclude_run_id=None):
    """True when [start, end) collides with any non-cancelled run on the deck,
    widened on both sides by the oven's changeover buffer."""
    buffer_minutes = oven["changeover_buffer_minutes"]
    for other in db.runs.values():
        if exclude_run_id is not None and other["id"] == exclude_run_id:
            continue
        if other.get("oven_id") != oven["id"]:
            continue
        if other.get("deck_index") != deck_index:
            continue
        if other["execution_status"] == "CANCELLED":
            continue
        other_product = db.products.get(other["product_id"])
        if other_product is None:
            continue
        other_interval = bake_interval(other, other_product)
        if other_interval is None:
            continue
        other_start, other_end = other_interval
        if start < add_minutes(other_end, buffer_minutes) and other_start < add_minutes(end, buffer_minutes):
            return True
    return False


# ---------------------------------------------------------------------------
# custom cakes (PRD 3.7)
# ---------------------------------------------------------------------------

def decoration_units(complexity, tier_count):
    return DECORATION_UNITS_PER_TIER[complexity] * int(tier_count)


def decoration_lead_minutes(complexity, tier_count, allergen_free_required):
    minutes = DECORATION_LEAD_BASE_MINUTES[complexity] + 30 * int(tier_count)
    if allergen_free_required:
        minutes += 45
    return minutes


def cake_quote(product, complexity, tier_count, rush_requested):
    """The five ordered steps of PRD 3.7; each percentage rounds at its step."""
    units = decoration_units(complexity, tier_count)
    subtotal = int(product["unit_retail_cents"]) * int(tier_count) + DECORATION_UNIT_CENTS * units
    if not rush_requested:
        rush_fee = 0
    elif subtotal < 5000:
        rush_fee = 800
    elif subtotal < 15000:
        rush_fee = cents(dec(subtotal) * Decimal("0.12"))
    else:
        rush_fee = cents(dec(subtotal) * Decimal("0.08"))
    inflated = subtotal + rush_fee
    if inflated >= 20000:
        discount = cents(dec(inflated) * Decimal("0.10"))
    elif inflated >= 10000:
        discount = cents(dec(inflated) * Decimal("0.05"))
    else:
        discount = 0
    total = subtotal + rush_fee - discount
    return units, subtotal, rush_fee, discount, total


def slots_overlap(start_a, end_a, start_b, end_b):
    """PRD 3.7: symmetric half-open overlap with no buffer."""
    return start_a < end_b and start_b < end_a


# ---------------------------------------------------------------------------
# purchasing (PRD 3.8)
# ---------------------------------------------------------------------------

def cost_order_line(ingredient, required_units, freight_pct):
    """cases (round up), ordered_units, line_cost_cents (half-up, per line)."""
    case_pack = int(ingredient["case_pack_units"])
    cases = ceil_int(dec(required_units) / dec(case_pack))
    ordered_units = cases * case_pack
    base = dec(ordered_units) * dec(ingredient["unit_cost_cents"])
    line_cost = cents(base * (Decimal("1") + dec(freight_pct)))
    return cases, ordered_units, line_cost


def shelf_life_cap(ingredient):
    return int(ingredient["daily_usage_units"]) * int(ingredient["shelf_life_days"])


def auto_reorder_topup(ingredient):
    top_up = 2 * int(ingredient["reorder_point_units"]) - int(ingredient["on_hand_units"])
    return top_up if top_up > 0 else 0


# ---------------------------------------------------------------------------
# plan walk arithmetic (PRD 3.3)
# ---------------------------------------------------------------------------

def effective_demand(forecasted_units, dow):
    return ceil_int(dec(forecasted_units) * DOW_UPLIFT[dow])


def required_racks(demand, units_per_rack):
    return ceil_int(dec(demand) / dec(units_per_rack))


def affordable_racks(product, remaining_labor, required):
    rate = per_rack_labor(product)
    if rate == 0:
        return required
    slack = dec(remaining_labor) - dec(product["setup_labor_minutes"])
    if slack <= 0:
        return 0
    return max(0, floor_int(slack / rate))


def ratio4(numerator, denominator):
    if not denominator:
        return q4(0)
    return q4(dec(numerator) / dec(denominator))
