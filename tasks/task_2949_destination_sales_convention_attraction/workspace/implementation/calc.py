"""The calculation rules of PRD 2.5, 3.1, 3.3, 3.6, 3.7 and 3.9.

Every rule here is pure arithmetic over rows already fetched by the caller:
component-level rounding precedes summation, selection bands are evaluated on
the input they name, counts use floor and person counts round half-up.
"""

import datetime
from decimal import Decimal, ROUND_FLOOR

import domain
import queries
from store import db, ordered
from util import date_at_midnight, money, round_int

HOUR = datetime.timedelta(hours=1)


# --------------------------------------------------------------------------
# dates and windows
# --------------------------------------------------------------------------
def event_nights(arrival_date, departure_date):
    """The whole number of days from arrival_date to departure_date."""
    return (departure_date - arrival_date).days


def windows_conflict(a_in, a_out, b_in, b_out, turnaround_hours):
    """PRD 3.3: a single-sided buffer applied to the earlier edge of each hold.
    Two holds conflict when, and only when, the first hold's move_in_start
    pulled back by the buffer is strictly earlier than the second hold's
    move_out_end AND the second hold's move_in_start pulled back by the buffer
    is strictly earlier than the first hold's move_out_end.  Both comparisons
    are strict, so exact adjacency at the buffer edge is permitted."""
    buffer = turnaround_hours * HOUR
    return (a_in - buffer) < b_out and (b_in - buffer) < a_out


def holds_conflict(hold_a, hold_b, hall):
    return windows_conflict(
        hold_a["move_in_start"], hold_a["move_out_end"],
        hold_b["move_in_start"], hold_b["move_out_end"],
        hall["turnaround_hours"],
    )


# --------------------------------------------------------------------------
# planner relationship score (PRD 3.1)
# --------------------------------------------------------------------------
def relationship_score(definite_count, room_nights, lost_count):
    """Twelve points per definite convention in scope, plus one point for every
    full 500 room nights in scope capped at 40 points, minus five points per
    lost lead in scope, clamped into 0..100 as an integer."""
    room_night_term = min(int(room_nights) // domain.SCORE_ROOM_NIGHTS_PER_POINT,
                          domain.SCORE_ROOM_NIGHT_CAP)
    raw = (domain.SCORE_POINTS_PER_DEFINITE * int(definite_count)
           + room_night_term
           - domain.SCORE_POINTS_PER_LOST * int(lost_count))
    if raw < domain.SCORE_MIN:
        return domain.SCORE_MIN
    if raw > domain.SCORE_MAX:
        return domain.SCORE_MAX
    return raw


def tier_for(score_lifetime):
    if score_lifetime >= domain.TIER_A_MIN_SCORE:
        return "TIER_A"
    if score_lifetime >= domain.TIER_B_MIN_SCORE:
        return "TIER_B"
    return "TIER_C"


def rolling_window_start():
    return db.clock - datetime.timedelta(days=domain.ROLLING_WINDOW_DAYS)


# --------------------------------------------------------------------------
# incentive cap (PRD 3.7) -- four pinned steps
# --------------------------------------------------------------------------
def band_ceiling(total_room_nights):
    """A marginal band ladder over the lead's total_room_nights_requested."""
    remaining = int(total_room_nights)
    first = min(remaining, domain.BAND_1_ROOM_NIGHTS)
    remaining -= first
    second = min(remaining, domain.BAND_2_ROOM_NIGHTS)
    remaining -= second
    third = remaining
    total = (Decimal(first) * domain.BAND_1_RATE
             + Decimal(second) * domain.BAND_2_RATE
             + Decimal(third) * domain.BAND_3_RATE)
    return money(total)


def coverage_factor(block_coverage_pct):
    pct = Decimal(block_coverage_pct)
    if pct >= domain.COVERAGE_FULL_THRESHOLD:
        return domain.COVERAGE_FACTOR_FULL
    if pct >= domain.COVERAGE_MID_THRESHOLD:
        return domain.COVERAGE_FACTOR_MID
    return domain.COVERAGE_FACTOR_LOW


def incentive_cap(opportunity, planner, estimate, fund=None):
    """Band ceiling, then the tier-keyed lodging-tax yield ceiling, then the
    coverage factor applied to the already-rounded smaller ceiling, then the
    clamp down to the named fund's uncommitted_amount (skipped at request time
    because no fund has been named yet)."""
    band = band_ceiling(opportunity["total_room_nights_requested"])
    rate = domain.TIER_YIELD_RATES[planner["tier"]]
    tax_yield = estimate["lodging_tax_yield_amount"] if estimate else Decimal("0.00")
    yield_ceiling = money(Decimal(tax_yield) * rate)
    smaller = band if band < yield_ceiling else yield_ceiling
    cap = money(smaller * coverage_factor(opportunity["block_coverage_pct"]))
    if fund is not None and cap > fund["uncommitted_amount"]:
        cap = money(fund["uncommitted_amount"])
    return cap


# --------------------------------------------------------------------------
# fund charge composition (PRD 3.7)
# --------------------------------------------------------------------------
def admin_fee_rate(gross):
    """Selected from the gross figure only, never re-derived from the total."""
    if gross < domain.FEE_BAND_1_CEILING:
        return domain.FEE_BAND_1_RATE
    if gross < domain.FEE_BAND_2_CEILING:
        return domain.FEE_BAND_2_RATE
    return domain.FEE_BAND_3_RATE


def charge_composition(gross):
    gross = money(gross)
    fee = money(gross * admin_fee_rate(gross))
    return fee, money(gross + fee)


def payback_ratio(lodging_tax_yield_amount, total_charge_amount):
    if total_charge_amount == 0:
        return None
    return money(Decimal(lodging_tax_yield_amount) / Decimal(total_charge_amount))


# --------------------------------------------------------------------------
# economic impact estimates (PRD 3.6)
# --------------------------------------------------------------------------
def estimate_tail(lodging, delegate, exhibitor):
    direct = money(lodging) + money(delegate) + money(exhibitor)
    total_impact = money(direct * domain.INDIRECT_MULTIPLIER)
    tax_yield = money(Decimal(lodging) * domain.LODGING_TAX_RATE)
    return direct, total_impact, tax_yield


def provisional_figures(opportunity):
    basis = opportunity["total_room_nights_requested"]
    lodging = money(Decimal(basis) * opportunity["rate_ceiling_amount"])
    delegate = money(Decimal(opportunity["attendance_estimate"])
                     * Decimal(opportunity["event_nights"])
                     * domain.DELEGATE_DAILY_SPEND)
    exhibitor = money(Decimal(opportunity["exhibit_sqft_requested"])
                      * domain.EXHIBITOR_SPEND_PER_SQFT)
    return basis, lodging, delegate, exhibitor


def eligible_pickups(opportunity_id):
    """Pickup rows under commitments of this lead in COMMITTED or RELEASED,
    ordered by night_date ascending with created_at ascending as tiebreaker.
    Rows under a WITHDRAWN commitment are excluded entirely."""
    rows = []
    for commitment in queries.commitments_of_opportunity(opportunity_id):
        if commitment["status"] not in ("COMMITTED", "RELEASED"):
            continue
        rows.extend(queries.pickups_of_commitment(commitment["id"]))
    return sorted(rows, key=lambda r: (r["night_date"], r["created_at"], r["_seq"]))


def final_figures(opportunity):
    pickups = eligible_pickups(opportunity["id"])
    basis = sum(p["rooms_picked_up"] for p in pickups)
    lodging = Decimal("0.00")
    for p in pickups:
        lodging += money(Decimal(p["rooms_picked_up"]) * p["rate_charged_amount"])
    lodging = money(lodging)
    person_nights = round_int(Decimal(basis) * domain.OCCUPANCY_PERSONS_PER_ROOM)
    delegate = money(Decimal(person_nights) * domain.DELEGATE_DAILY_SPEND)
    confirmed_sqft = 0
    for hold in queries.holds_of_opportunity(opportunity["id"]):
        if hold["status"] != "CONFIRMED":
            continue
        hall = db.halls.get(hold["center_hall_id"])
        if hall is not None:
            confirmed_sqft += hall["exhibit_sqft"]
    capped = min(confirmed_sqft, opportunity["exhibit_sqft_requested"])
    exhibitor = money(Decimal(capped) * domain.EXHIBITOR_SPEND_PER_SQFT)
    return basis, lodging, delegate, exhibitor


# --------------------------------------------------------------------------
# attrition settlement (PRD 3.9)
# --------------------------------------------------------------------------
def attrition_for_commitment(commitment):
    """Only COMMITTED or RELEASED commitments participate, and a commitment with
    no pickup record at all is skipped entirely rather than assessed."""
    if commitment["status"] not in ("COMMITTED", "RELEASED"):
        return 0, Decimal("0.00")
    if not queries.pickups_of_commitment(commitment["id"]):
        return 0, Decimal("0.00")
    allowance = int((Decimal(commitment["committed_room_nights"])
                     * domain.ATTRITION_ALLOWANCE_FRACTION).to_integral_value(
                         rounding=ROUND_FLOOR))
    shortfall = allowance - commitment["picked_up_room_nights"]
    if shortfall < 0:
        shortfall = 0
    rate = commitment["rate_offered_amount"] or Decimal("0.00")
    damages = money(Decimal(shortfall) * rate * domain.ATTRITION_DAMAGE_RATE)
    return shortfall, damages


def settlement_amount(opportunity_id):
    """Per-commitment damages rounded first, then added in order of the
    property's name ascending with the commitment's created_at as tiebreaker."""
    rows = queries.commitments_of_opportunity(opportunity_id)

    def sort_key(commitment):
        hotel = db.hotels.get(commitment["hotel_id"])
        return (hotel["name"] if hotel else "", commitment["created_at"],
                commitment["_seq"])

    total = Decimal("0.00")
    for commitment in sorted(rows, key=sort_key):
        total += money(commitment["attrition_damages_amount"])
    return money(total)


# --------------------------------------------------------------------------
# board report rollup (PRD 3.9)
# --------------------------------------------------------------------------
def _in_window(instant, start, end):
    """Half-open window: at or after start, strictly before end."""
    return instant is not None and start <= instant < end


def board_rollup(period_start, period_end):
    """Every board figure, each keyed on the instant the PRD pins for it.

    Production is keyed on definite_at, lost business and attrition recovery on
    updated_at, incentive spend on the decision's created_at and recognized
    revenue on the receipt's received_at.  Rows falling outside the window are
    excluded even when their opportunity is otherwise in scope.
    """
    start = date_at_midnight(period_start)
    end = date_at_midnight(period_end)

    definite_count = 0
    definite_room_nights = 0
    lost_count = 0
    lost_by_reason = {}
    attrition_recovered = Decimal("0.00")

    for opportunity in ordered(list(db.opportunities.values())):
        stage = opportunity["sales_stage"]
        if stage in ("DEFINITE", "SERVICED") and _in_window(
                opportunity["definite_at"], start, end):
            definite_count += 1
            definite_room_nights += opportunity["definite_room_nights"]
        if stage == "LOST" and _in_window(opportunity["updated_at"], start, end):
            lost_count += 1
            reason = opportunity["lost_reason"]
            lost_by_reason[reason] = (lost_by_reason.get(reason, 0)
                                      + opportunity["total_room_nights_requested"])
        if stage == "SERVICED" and _in_window(
                opportunity["updated_at"], start, end):
            attrition_recovered += money(opportunity["attrition_settlement_amount"])

    # any reason whose total would be zero is omitted from the map entirely
    lost_by_reason = {k: v for k, v in lost_by_reason.items() if v != 0}

    incentive_spend = Decimal("0.00")
    for decision in ordered(list(db.decisions.values())):
        if decision["decision"] not in ("APPROVED", "REDUCED"):
            continue
        if _in_window(decision["created_at"], start, end):
            incentive_spend += money(decision["total_charge_amount"])

    tax_recognized = Decimal("0.00")
    for receipt in ordered(list(db.receipts.values())):
        if _in_window(receipt["received_at"], start, end):
            tax_recognized += money(receipt["amount"])

    if definite_room_nights > 0:
        cost_per = money(incentive_spend / Decimal(definite_room_nights))
    else:
        cost_per = None

    return {
        "definite_opportunity_count": definite_count,
        "definite_room_nights": definite_room_nights,
        "lost_opportunity_count": lost_count,
        "lost_room_nights_by_reason": lost_by_reason,
        "incentive_spend_committed_amount": money(incentive_spend),
        "lodging_tax_recognized_amount": money(tax_recognized),
        "cost_per_definite_room_night": cost_per,
        "attrition_recovered_amount": money(attrition_recovered),
    }
