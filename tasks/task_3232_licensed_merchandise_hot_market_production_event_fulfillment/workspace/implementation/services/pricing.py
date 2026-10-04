"""Calculation rules: hot-market commitment, rush delivery, wholesale totals,
write-downs and counterfeit exposure.

Every constant below is read from the task's calculation table; the evaluation
order of each rule is pinned by the specification and implemented literally.
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from services.ledger import round_half_up, to_cents

# --- hot_market_capacity_commitment --------------------------------------
MAJOR_MARKET_DEMAND_UNITS = 100000
REGIONAL_DEMAND_UNITS = 25000
PROBABILITY_FLOOR = Decimal("0.05")
RUSH_HOURS = 6
RUSH_ADDITIONAL_FACTOR = Decimal("1.5")
SAME_HOUR_FACTOR = Decimal("2.0")
TIER_RESIDUAL = {"LOCAL": 25, "REGIONAL": 50, "MAJOR_MARKET": 0}

# --- rush_delivery_commitment --------------------------------------------
RUSH_WINDOW_HOURS = 24
STANDARD_WINDOW_HOURS = 72
RUSH_WEIGHT = Decimal("0.9")
STANDARD_WEIGHT = Decimal("0.1")

# --- wholesale_fulfillment_total -----------------------------------------
CHANNEL_RATE_CENTS_PER_UNIT = {"VENUE_RETAIL": 12, "EVENT_POPUP": 9, "ECOM": 5}
RUSH_SURCHARGE_CENTS_PER_UNIT = 2
DONATION_FLAT_CENTS = 100
DESTROY_PENALTY_CENTS_PER_UNIT = 4
DONATE_PENALTY_CENTS_PER_UNIT = 0

# --- demand_collapse_write_down ------------------------------------------
STANDARD_RECOVERY_PCT = Decimal("0.6")
FULL_LOSS_RECOVERY_PCT = Decimal("0.0")
WRITE_DOWN_RESET_HOURS = 48
POST_EVENT_MARKUP = Decimal("2.5")
HOT_MARKET_TRIGGERS = ("CHAMPIONSHIP_WIN", "MILESTONE", "ATHLETE_TRANSACTION")

# --- counterfeit_exposure -------------------------------------------------
EXPOSURE_VALUATION_CENTS_PER_UNIT = 1450
LEAKAGE_RATE_OF_GROSS = Decimal("0.6")
DETERRENCE_MULTIPLIER = Decimal("2.5")
CONFIRMED_FLOOR_CENTS = 500


def demand_tier(expected_demand_qty):
    """Step 1, inclusive at each lower edge."""
    if expected_demand_qty >= MAJOR_MARKET_DEMAND_UNITS:
        return "MAJOR_MARKET"
    if expected_demand_qty >= REGIONAL_DEMAND_UNITS:
        return "REGIONAL"
    return "LOCAL"


def hour_factor(hours_to_outcome):
    """Step 3, inclusive at each lower edge."""
    if hours_to_outcome > RUSH_HOURS:
        return Decimal("1.0")
    if hours_to_outcome > 1:
        return RUSH_ADDITIONAL_FACTOR
    return SAME_HOUR_FACTOR


def is_first_of_team_trigger(run):
    """Step 4/5 precedence: the FIRST run created for a given
    (team_code, trigger_type) pair is the provisional variant; the second and
    every later run is the committed-final variant.  Ordering is by created_at,
    ties broken by ascending id of creation (never a random field)."""
    siblings = [r for r in db.store.production_orders.values()
                if r.get("team_code") == run.get("team_code")
                and r.get("trigger_type") == run.get("trigger_type")
                and r["id"] != run["id"]]
    for sibling in siblings:
        if db.creation_key(sibling) < db.creation_key(run):
            return False
    return True


def capacity_commitment_units(expected_demand_qty, win_probability_pct,
                              hours_to_outcome, tier, first_variant):
    """Pinned order: tier, then p, then hour_factor, then the residual, then the
    final floor.  Never recomputed from a value it has already written."""
    y = Decimal(int(expected_demand_qty))
    p = max(Decimal(str(win_probability_pct)), PROBABILITY_FLOOR)
    hf = hour_factor(hours_to_outcome)
    if first_variant:
        value = int((y * p * hf).to_integral_value(rounding="ROUND_CEILING"))
    else:
        base = int((y * p).to_integral_value(rounding="ROUND_FLOOR"))
        value = base + TIER_RESIDUAL[tier]
    floor_value = int((y * p / Decimal("2")).to_integral_value(rounding="ROUND_CEILING"))
    return max(value, floor_value)


def required_allocation_units(expected_demand_qty, win_probability_pct, tier):
    """The value the run would have needed: its own floor plus the alignment the
    tier requires (ERR_UNBALANCED_ALLOCATION otherwise)."""
    y = Decimal(int(expected_demand_qty))
    p = max(Decimal(str(win_probability_pct)), PROBABILITY_FLOOR)
    floor_value = int((y * p / Decimal("2")).to_integral_value(rounding="ROUND_CEILING"))
    return floor_value + TIER_RESIDUAL[tier]


# --- rush_delivery_commitment --------------------------------------------

def _window_capability_for(print_type):
    """PENNANT goods run on the BASE capability (PRD 2.9)."""
    return "BASE" if print_type in ("BASE", "PENNANT") else print_type


def run_supported_types(run):
    types = set()
    for layer_id in run.get("layer_ids") or []:
        layer = db.store.print_layers.get(layer_id)
        if layer is not None:
            types.add(_window_capability_for(layer.get("print_type")))
    return types


def _window_supports_run(window, run):
    supported = run_supported_types(run)
    if not supported:
        return True
    return window.get("print_type") in supported


def rush_delivery_points(run):
    """Weighted rush-or-standard delivery points over the run's HELD
    reservations, rounded HALF_UP to 2 decimals."""
    rush_qty = 0
    standard_qty = 0
    reservations = sorted(db.store.print_reservations.values(),
                          key=lambda r: (str(r.get("reserved_at") or ""),
                                         int(r.get("quantity", 0) or 0),
                                         str(r.get("id") or "")))
    for reservation in reservations:
        if reservation.get("reservation_state") != "HELD":
            continue
        window = db.store.print_capacities.get(reservation.get("print_capacity_id"))
        if window is None or not _window_supports_run(window, run):
            continue
        span = db.hours_between(reservation.get("needed_by"), window.get("window_start"))
        if span is None:
            standard_qty += int(reservation.get("quantity", 0) or 0)
            continue
        if span <= RUSH_WINDOW_HOURS:
            rush_qty += int(reservation.get("quantity", 0) or 0)
        else:
            standard_qty += int(reservation.get("quantity", 0) or 0)
    points = round_half_up(RUSH_WEIGHT * rush_qty + STANDARD_WEIGHT * standard_qty)
    return points


def rush_commitment_floor_units(points):
    """commitment_floor_units = ceil(rush_delivery_points / 2)."""
    return int((Decimal(points) / Decimal("2")).to_integral_value(rounding="ROUND_CEILING"))


def refresh_rush_delivery_points(run):
    run["rush_delivery_points"] = int(rush_delivery_points(run))
    return run["rush_delivery_points"]


# --- wholesale_fulfillment_total -----------------------------------------

def quote_wholesale(channel, quantity, rush_flag, donation_recipient_code):
    """Per-term HALF_UP then summed in the pinned order: channel term, then rush
    surcharge term, then the flat donation term."""
    qty = Decimal(int(quantity))
    channel_term = round_half_up(qty * Decimal(CHANNEL_RATE_CENTS_PER_UNIT.get(channel, 0)))
    rush_term = round_half_up(qty * Decimal(RUSH_SURCHARGE_CENTS_PER_UNIT)) if rush_flag else Decimal("0.00")
    donation_term = Decimal(DONATION_FLAT_CENTS) if donation_recipient_code else Decimal("0.00")
    return to_cents(channel_term + rush_term + donation_term)


def destroy_weighted_total(quantity):
    """DESTROY branch: quantity * DESTROY_PENALTY_CENTS_PER_UNIT."""
    return to_cents(round_half_up(Decimal(int(quantity)) * Decimal(DESTROY_PENALTY_CENTS_PER_UNIT)))


def donate_weighted_total(quantity):
    """DONATE branch: quantity * DONATE_PENALTY_CENTS_PER_UNIT (no penalty)."""
    return to_cents(round_half_up(Decimal(int(quantity)) * Decimal(DONATE_PENALTY_CENTS_PER_UNIT)))


def returned_recognition(requested_wholesale_cents, return_quantity, unit_cost_cents):
    """RETURNED rail: max(0, requested - return_quantity * unit_cost) HALF_UP."""
    value = Decimal(int(requested_wholesale_cents or 0)) - \
        Decimal(int(return_quantity or 0)) * Decimal(int(unit_cost_cents or 0))
    return max(0, to_cents(round_half_up(value)))


# --- demand_collapse_write_down ------------------------------------------

def order_write_down(quantity, unit_cost_cents):
    """Target B: quantity * unit_cost_cents * POST_EVENT_MARKUP (2.5)."""
    value = Decimal(int(quantity or 0)) * Decimal(int(unit_cost_cents or 0)) * POST_EVENT_MARKUP
    return to_cents(round_half_up(value))


def run_write_down(trigger_type, lost_units, unit_cost_cents):
    """Target A: destroyed_qty * unit_cost_cents * (1 - recovery_pct), where the
    recovery share depends on how the run came to exist."""
    recovery = STANDARD_RECOVERY_PCT if trigger_type == "STANDARD" else FULL_LOSS_RECOVERY_PCT
    value = Decimal(int(lost_units or 0)) * Decimal(int(unit_cost_cents or 0)) * (Decimal("1") - recovery)
    return to_cents(round_half_up(value))


def discharged_wholesale(run):
    """realized_wholesale_cents over the run's DELIVERED and RETURNED orders,
    in created_at order."""
    total = 0
    for order in db.created_order(list(db.store.fulfillment_orders.values())):
        if order.get("production_order_id") != run["id"]:
            continue
        if order.get("status") in ("DELIVERED", "RETURNED"):
            total += int(order.get("realized_wholesale_cents", 0) or 0)
    return total


# --- counterfeit_exposure -------------------------------------------------

def counterfeit_exposure(suspect_quantity, royalty_rate_pct):
    """leakage = round_half_up(units * 1450 * 0.6 * rate);
    penalty = round_half_up(leakage * 2.5); total floored at 500 when confirmed."""
    leakage = round_half_up(Decimal(int(suspect_quantity or 0))
                            * Decimal(EXPOSURE_VALUATION_CENTS_PER_UNIT)
                            * LEAKAGE_RATE_OF_GROSS
                            * Decimal(str(royalty_rate_pct)))
    penalty = round_half_up(leakage * DETERRENCE_MULTIPLIER)
    leakage_cents = to_cents(leakage)
    penalty_cents = to_cents(penalty)
    total = leakage_cents + penalty_cents
    if total < CONFIRMED_FLOOR_CENTS:
        total = CONFIRMED_FLOOR_CENTS
    return leakage_cents, penalty_cents, total