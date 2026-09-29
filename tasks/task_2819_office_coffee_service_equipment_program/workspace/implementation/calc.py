"""Every calculation of PRD 3, in exact rational arithmetic.

Each rounding step happens exactly where the prose names it and never a second
time on an aggregate that has already been rounded (PRD 2.6).
"""
from datetime import timedelta
from fractions import Fraction

from numbers_util import (BPS_UNITY, MICROS_PER_CENT, apply_bps, ceil_int, floor_int,
                          micros_to_cents, round_half_up)
from store import db, now, ordered
from timeutil import UTC

# ---------------------------------------------------------------- shelf statuses

def stock_status(on_hand_units, reorder_point_units):
    """PRD 3.2: always derived, never supplied."""
    if on_hand_units == 0:
        return "STOCKOUT"
    if on_hand_units > 0 and on_hand_units <= reorder_point_units:
        return "LOW"
    return "IN_STOCK"


# ------------------------------------------------------- consumption forecasting

BREW_STYLE_FACTOR = {
    "DRIP": Fraction(100, 100),
    "SINGLE_CUP": Fraction(115, 100),
    "ESPRESSO": Fraction(85, 100),
}
CUPS_PER_PERSON_PER_DAY = Fraction(18, 10)
COVER_WEEKS = 2
PEAK_FACTOR = Fraction(35, 100)
TRAILING_WINDOW_DAYS = 28
TRAILING_UPLIFT_BPS = 11000
REORDER_BPS = 4000

UNIT_FACTOR = {
    "COFFEE": Fraction(9, 100),
    "CREAMER": Fraction(50, 100),
    "TEA": Fraction(5, 100),
    "WATER": Fraction(1, 100),
    "PANTRY": Fraction(40, 100),
}


def forecast_cups_per_week(headcount, days_per_week, brew_style):
    """headcount x 1.8 x occupied days x brew-style factor, rounded up."""
    raw = (Fraction(headcount) * CUPS_PER_PERSON_PER_DAY * Fraction(days_per_week)
           * BREW_STYLE_FACTOR[brew_style])
    return ceil_int(raw)


def required_peak_cups_per_hour(cups_per_week, days_per_week):
    """weekly forecast / occupied days x 0.35, rounded up; no intermediate rounding."""
    return ceil_int(Fraction(cups_per_week, days_per_week) * PEAK_FACTOR)


def headcount_par_units(cups_per_week, category):
    """weekly forecast x two-week cover x per-cup unit factor, rounded up."""
    return ceil_int(Fraction(cups_per_week) * COVER_WEEKS * UNIT_FACTOR[category])


def trailing_par_units(observed_units):
    """(observed / 4) x two-week cover x 11000 bps / 10000, rounded up."""
    weekly = Fraction(observed_units, 4)
    return ceil_int(weekly * COVER_WEEKS * Fraction(TRAILING_UPLIFT_BPS, BPS_UNITY))


def reorder_point_units(par_units):
    """par x 4000 bps / 10000, rounded up."""
    return ceil_int(Fraction(par_units) * Fraction(REORDER_BPS, BPS_UNITY))


# -------------------------------------------------------- equipment sizing (3.2)

def select_recommended_model(headcount, required_peak):
    """Smallest sufficient brewer: capacity ascending, then monthly rent ascending,
    then created_at ascending. Physical asset availability plays no part."""
    candidates = [
        m for m in db.equipment_models.values()
        if m["min_headcount"] <= headcount <= m["max_headcount"]
        and m["cups_per_hour_capacity"] >= required_peak
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (m["cups_per_hour_capacity"], m["monthly_rent_cents"],
                                   m["created_at"], m["_seq"]))
    return candidates[0]["id"]


# ------------------------------------------------------ collection lookup helpers

def site_par_lines(site_id):
    return [p for p in db.par_levels.values() if p["site_id"] == site_id]


def site_visits(site_id):
    return [v for v in db.service_visits.values() if v["site_id"] == site_id]


def account_sites(account_id):
    return [s for s in db.sites.values() if s["account_id"] == account_id]


def site_placements(site_id):
    return [p for p in db.equipment_placements.values() if p["site_id"] == site_id]


def account_placements(account_id):
    ids = set(s["id"] for s in account_sites(account_id))
    return [p for p in db.equipment_placements.values() if p["site_id"] in ids]


def par_line_for(site_id, product_id):
    for p in db.par_levels.values():
        if p["site_id"] == site_id and p["product_id"] == product_id:
            return p
    return None


def active_placement_of_asset(asset_id):
    for p in db.equipment_placements.values():
        if p["asset_id"] == asset_id and p["placement_status"] == "ACTIVE":
            return p
    return None


def active_placement_of_site(site_id):
    for p in ordered(site_placements(site_id)):
        if p["placement_status"] == "ACTIVE":
            return p
    return None


def invoice_lines_of(invoice_id):
    return ordered([l for l in db.invoice_lines.values() if l["invoice_id"] == invoice_id])


# ------------------------------------------------------- escalation score (3.5)

ESCALATION_THRESHOLD = Fraction(40)
ESCALATION_CAP = Fraction(100)
MISSED_VISIT_WINDOW_DAYS = 28


def descale_overdue(asset, current=None):
    """last_descale_at advanced by the model's descale_interval_days is at or before
    the current instant."""
    current = current or now()
    model = db.equipment_models.get(asset["model_id"])
    if model is None or asset.get("last_descale_at") is None:
        return False
    due = asset["last_descale_at"] + timedelta(days=model["descale_interval_days"])
    return due <= current


def escalation_score(site):
    """PRD 3.5. Weights are multiples of one half, so the score is exact."""
    current = now()
    stockout = 0
    below_reorder = 0
    for line in site_par_lines(site["id"]):
        if line["on_hand_units"] == 0 and line["cumulative_delivered_units"] > 0:
            stockout += 1
        elif 0 < line["on_hand_units"] <= line["reorder_point_units"]:
            below_reorder += 1
    overdue_descale = 0
    for placement in site_placements(site["id"]):
        if placement["placement_status"] != "ACTIVE":
            continue
        asset = db.equipment_assets.get(placement["asset_id"])
        if asset is not None and descale_overdue(asset, current):
            overdue_descale += 1
    cutoff = current - timedelta(days=MISSED_VISIT_WINDOW_DAYS)
    missed = 0
    for visit in site_visits(site["id"]):
        if visit["visit_status"] == "CANCELLED" and visit["window_start"] >= cutoff:
            missed += 1
    raw = (Fraction(stockout) * 20 + Fraction(below_reorder) * Fraction(15, 2)
           + Fraction(overdue_descale) * 15 + Fraction(missed) * 10)
    return min(ESCALATION_CAP, raw)


def score_to_number(score):
    """The one non-integer stored value, carried to one decimal place."""
    return float(score)


# ---------------------------------------------- consumption debit and pricing (3.5)

COVER_DAYS = 14
SECONDS_PER_DAY = 86400


def consumption_debit(par_line, window_start):
    """Elapsed days from last_service_at to the visit's window_start (floor of the
    second count / 86400), times par_units / 14 carried exactly, floored, then
    clamped to the shelf quantity."""
    delta = window_start - par_line["last_service_at"]
    seconds = delta.days * SECONDS_PER_DAY + delta.seconds
    elapsed_days = floor_int(Fraction(seconds, SECONDS_PER_DAY))
    daily_draw = Fraction(par_line["par_units"], COVER_DAYS)
    modelled = floor_int(daily_draw * elapsed_days)
    return min(par_line["on_hand_units"], modelled)


def effective_unit_price_micros(product, account):
    """Snapshot taken at completion; never recomputed downstream."""
    if product.get("green_coffee_linked"):
        return apply_bps(product["base_unit_price_micros"], account["green_price_factor_bps"])
    return product["base_unit_price_micros"]


def line_amount_cents(qty_units, unit_price_micros):
    """qty x unit price / 10000, rounded half up, individually per line."""
    return micros_to_cents(qty_units, unit_price_micros)


# ----------------------------------------------------- trailing rollups (3.1, 3.7)

TRAILING_PURCHASE_DAYS = 90
ALLIED_WINDOW_DAYS = 90


def _in_left_exclusive_window(instant, current, days):
    """(current - days, current] - a visit exactly `days` old is outside."""
    return (current - timedelta(days=days)) < instant <= current


def trailing_purchase_cents(site_id):
    """PRD 3.7: only this site's COMPLETED visits, 90-day left-exclusive window,
    each line rounded individually and the rounded amounts then summed."""
    current = now()
    total = 0
    for visit in site_visits(site_id):
        if visit["visit_status"] != "COMPLETED":
            continue
        if not _in_left_exclusive_window(visit["window_start"], current, TRAILING_PURCHASE_DAYS):
            continue
        for line in visit["lines"]:
            delivered = line.get("delivered_units") or 0
            if delivered <= 0:
                continue
            total += line_amount_cents(delivered, line["effective_unit_price_micros"])
    return total


def allied_attachment_bps(account_id):
    """PRD 3.1: allied bucket x 10000 / (coffee + allied), rounded half up; 0 when
    the account has taken no delivery in the window."""
    current = now()
    coffee = 0
    allied = 0
    for site in account_sites(account_id):
        for visit in site_visits(site["id"]):
            if visit["visit_status"] != "COMPLETED":
                continue
            if not _in_left_exclusive_window(visit["window_start"], current, ALLIED_WINDOW_DAYS):
                continue
            for line in visit["lines"]:
                delivered = line.get("delivered_units") or 0
                if delivered <= 0:
                    continue
                amount = line_amount_cents(delivered, line["effective_unit_price_micros"])
                product = db.product_items.get(line["product_id"])
                category = product["category"] if product else None
                if category == "COFFEE":
                    coffee += amount
                else:
                    allied += amount
    denominator = coffee + allied
    if denominator == 0:
        return 0
    return round_half_up(Fraction(allied * BPS_UNITY, denominator))


# --------------------------------------------- unreturned asset pricing (PRD 3.3)

DEPRECIATION_BPS_PER_MONTH = 150
RESIDUAL_FLOOR_BPS = 3000
RETRIEVAL_TRIP_FEE_CENTS = 7500
MONTH_DAYS = 30


def months_in_service(anchor, current):
    """Elapsed time from the anchor to the current instant / 30 days, floored."""
    delta = current - anchor
    seconds = delta.days * SECONDS_PER_DAY + delta.seconds
    return floor_int(Fraction(seconds, MONTH_DAYS * SECONDS_PER_DAY))


def unreturned_asset_charge(asset, anchor):
    """Residual value + a flat 7500-cent retrieval trip fee. The model is always
    reached through the asset's own model_id."""
    model = db.equipment_models.get(asset["model_id"])
    list_value = model["list_value_cents"] if model else 0
    months = months_in_service(anchor, now())
    depreciated_bps = BPS_UNITY - DEPRECIATION_BPS_PER_MONTH * months
    if depreciated_bps < RESIDUAL_FLOOR_BPS:
        depreciated_bps = RESIDUAL_FLOOR_BPS
    residual = apply_bps(list_value, depreciated_bps)
    return residual + RETRIEVAL_TRIP_FEE_CENTS


# ------------------------------------------ equipment program charges (PRD 3.7)

LOAN_SHORTFALL_BPS = 3500
RENTAL_SHORTFALL_BPS = 2500
LOAN_MINIMUM_FLOOR_CENTS = 75000


def unmet_commitment_cents(placement):
    gap = placement["minimum_purchase_cents"] - placement["trailing_purchase_cents"]
    return gap if gap > 0 else 0


def shortfall_fee_cents(placement):
    """LOAN: 3500 bps of the unmet commitment. RENTAL: a flat 2500 bps of the FULL
    monthly rent, never of the prorated charge - which is what makes the rental
    component period-independent."""
    unmet = unmet_commitment_cents(placement)
    if placement["terms_type"] == "LOAN":
        return apply_bps(unmet, LOAN_SHORTFALL_BPS)
    if unmet == 0:
        return 0
    model = _model_of_placement(placement)
    monthly_rent = model["monthly_rent_cents"] if model else 0
    return apply_bps(monthly_rent, RENTAL_SHORTFALL_BPS)


def _model_of_placement(placement):
    asset = db.equipment_assets.get(placement["asset_id"])
    if asset is None:
        return None
    return db.equipment_models.get(asset["model_id"])


def rent_charge_cents(placement, period_start, period_end):
    """monthly rent x min(30, days active) / 30, rounded half up. The days active are
    a plain date difference with no inclusive-day adjustment."""
    if placement["terms_type"] != "RENTAL":
        return 0
    model = _model_of_placement(placement)
    if model is None:
        return 0
    start = max(period_start, placement["placed_at"]).astimezone(UTC).date()
    end = min(period_end, now()).astimezone(UTC).date()
    days_active = (end - start).days
    capped = min(MONTH_DAYS, days_active)
    return round_half_up(Fraction(model["monthly_rent_cents"] * capped, MONTH_DAYS))


# ------------------------------------------- green coffee repricing (PRD 3.9)

MOVEMENT_THRESHOLD_BPS = 800
PASS_THROUGH_BPS = 6000
ADJUSTMENT_CAP_BPS = 1500
FACTOR_FLOOR_BPS = 5000


def movement_bps(index_current_micros, index_baseline_micros):
    """Signed difference x 10000 / baseline, rounded half up."""
    delta = index_current_micros - index_baseline_micros
    return round_half_up(Fraction(delta * BPS_UNITY, index_baseline_micros))


def pass_through_bps(movement):
    """Movement x 6000 bps / 10000 rounded half up, then clamped to +/-1500. The cap
    is applied last and never re-rounds."""
    raw = apply_bps(movement, PASS_THROUGH_BPS)
    if raw > ADJUSTMENT_CAP_BPS:
        return ADJUSTMENT_CAP_BPS
    if raw < -ADJUSTMENT_CAP_BPS:
        return -ADJUSTMENT_CAP_BPS
    return raw


# ------------------------------------------- route windows and capacity (PRD 3.4)

def route_visits(route_id):
    return [v for v in db.service_visits.values() if v["route_id"] == route_id]


OCCUPYING_VISIT_STATUSES = ("SCHEDULED", "COMPLETED")


def route_window_conflict(route, window_start, window_end, exclude_visit_id=None):
    """The candidate is widened symmetrically by travel_buffer_minutes and treated as
    half-open, so exact abutment is never a collision."""
    buffer_delta = timedelta(minutes=route.get("travel_buffer_minutes") or 0)
    cand_start = window_start - buffer_delta
    cand_end = window_end + buffer_delta
    for visit in route_visits(route["id"]):
        if visit["id"] == exclude_visit_id:
            continue
        if visit["visit_status"] not in OCCUPYING_VISIT_STATUSES:
            continue
        if cand_start < visit["window_end"] and visit["window_start"] < cand_end:
            return True
    return False


def booked_minutes_on_date(route_id, service_date, exclude_visit_id=None):
    """Sum of planned_minutes over the route's SCHEDULED or COMPLETED visits whose
    window_start falls on the same UTC calendar date."""
    total = 0
    for visit in route_visits(route_id):
        if visit["id"] == exclude_visit_id:
            continue
        if visit["visit_status"] not in OCCUPYING_VISIT_STATUSES:
            continue
        if visit["window_start"].astimezone(UTC).date() == service_date:
            total += visit["planned_minutes"]
    return total


def route_booked_minutes_total(route_id):
    total = 0
    for visit in route_visits(route_id):
        if visit["visit_status"] in OCCUPYING_VISIT_STATUSES:
            total += visit["planned_minutes"]
    return total


# --------------------------------------------- loaner availability (PRD 3.6)

HOLDING_LOANER_STATUSES = ("OUT", "OVERDUE", "WRITTEN_OFF")


def loaner_window_conflict(asset_id, out_date, due_back_date, exclude_wo_id=None):
    """Closed date intervals on both sides, so an abutting same-day handoff IS a
    conflict - deliberately unlike the half-open route rule. A written-off loaner
    blocks forever; a returned one blocks through its return date plus one day."""
    for wo in db.work_orders.values():
        if wo["id"] == exclude_wo_id:
            continue
        if wo.get("loaner_asset_id") != asset_id:
            continue
        status = wo.get("loaner_status")
        if status in HOLDING_LOANER_STATUSES:
            held_start = wo["loaner_out_date"].astimezone(UTC).date()
            if held_start <= due_back_date:
                return True
        elif status == "RETURNED":
            held_start = wo["loaner_out_date"].astimezone(UTC).date()
            held_end = wo["loaner_returned_on"].astimezone(UTC).date() + timedelta(days=1)
            if out_date <= held_end and held_start <= due_back_date:
                return True
    return False


def descale_past_interval(asset, current=None):
    """The resolve gate of PRD 3.6 is STRICT where the escalation term of 3.5 is not:
    a preventive order is refused only once the elapsed time EXCEEDS the interval, so
    an asset exactly at its interval still signs off while already scoring 15 points."""
    current = current or now()
    model = db.equipment_models.get(asset["model_id"])
    if model is None or asset.get("last_descale_at") is None:
        return False
    due = asset["last_descale_at"] + timedelta(days=model["descale_interval_days"])
    return due < current


LOANER_WRITEOFF_DAYS = 30
RECONDITIONING_DAYS = 1
