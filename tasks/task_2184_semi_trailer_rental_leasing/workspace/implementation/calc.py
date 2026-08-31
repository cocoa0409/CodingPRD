"""Pinned calculation rules (PRD sections 2.6, 3.2, 3.3, 3.5, 3.6, 3.7, 3.8, 3.9)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store

# --- constants -------------------------------------------------------------
DROP_CHARGE_CENTS = 35000
MILEAGE_PRORATION_DAYS = 30

BASE_BY_TIER = {"A": 10, "B": 25, "C": 45}
CHARGEBACK_POINTS_PER_10000_CENTS = 2
ASSESSMENT_POINTS_EACH = 3
SCORE_FLOOR = 0
SCORE_CAP = 100
RISK_SCORE_MAX = 85
DECAY_AGE_DAYS = 180

BASE_DISPATCH_FEE_CENTS = 15000
BAND1_MAX_MILES = 250
BAND1_RATE_CENTS_PER_MILE = 260
BAND2_MAX_MILES = 600
BAND2_RATE_CENTS_PER_MILE = 215
BAND3_RATE_CENTS_PER_MILE = 185
DEADHEAD_RATE_CENTS_PER_MILE = 130
FUEL_SURCHARGE_PCT = Decimal("0.07")
FUEL_SURCHARGE_MILE_THRESHOLD = 500
MIN_CHARGE_CENTS = 40000

SEVERITY_MULTIPLIER = {
    "MINOR": Decimal("1.00"),
    "MODERATE": Decimal("1.25"),
    "MAJOR": Decimal("1.60"),
}
SEVERITY_POINTS = {"MINOR": 3, "MODERATE": 8, "MAJOR": 15}
DEDUCTIBLE_BY_TIER = {"A": 100000, "B": 150000, "C": 250000}
ADMIN_FEE_PCT = Decimal("0.08")

OOS_DAMAGE_POINT_THRESHOLD = 25

INBOUND_BUFFER_DAYS_BEFORE = 1
BRANCH_DWELL_DAYS_AFTER = 3

DEPRECIATION_RATE_PER_YEAR = Decimal("0.10")
DEPRECIATION_MONTH_DAYS = 30

LEASE_CREDIT_RATE = Decimal("0.12")
MAX_CREDIT_PCT = Decimal("0.30")
MIN_PURCHASE_OPTION_TERM_DAYS = 720


# --- numeric helpers -------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    return numerator // denominator


def floor_dec(value):
    return int(dec(value).to_integral_value(rounding="ROUND_FLOOR"))


def ceil_dec(value):
    return int(dec(value).to_integral_value(rounding="ROUND_CEILING"))


# --- trailer derivations ---------------------------------------------------
def trailer_damage_points(trailer):
    """Live damage-point sum, honouring the damage-repair watermark."""
    watermark = trailer.get("_last_damage_repair_seq")
    total = 0
    for a in store.damage_assessments.values():
        if a.get("trailer_id") != trailer["id"]:
            continue
        if a.get("status") not in ("SUBMITTED", "APPROVED"):
            continue
        if watermark is not None and a["_seq"] <= watermark:
            continue
        total += a.get("damage_points") or 0
    return total


def trailer_service_status(trailer):
    """First-match-wins precedence (PRD 3.7)."""
    ttype = store.trailer_types.get(trailer["trailer_type_id"])
    today = store.clock_date()
    expires = store.parse_date(trailer.get("dot_expires_on"))
    if not trailer.get("last_dot_passed", True) or (expires is not None and today >= expires):
        return "OOS_DOT_EXPIRED"
    if trailer_damage_points(trailer) >= OOS_DAMAGE_POINT_THRESHOLD:
        return "OOS_DAMAGE"
    if ttype is not None:
        interval = ttype.get("pm_interval_miles") or 0
        if trailer.get("hub_miles", 0) - trailer.get("last_pm_hub_miles", 0) >= interval:
            return "PM_DUE"
    return "SERVICEABLE"


def compute_dot_expires_on(last_inspection_date, ttype):
    base = store.parse_date(last_inspection_date)
    if base is None:
        return None
    return store.add_days(base, ttype.get("dot_inspection_interval_days") or 0).isoformat()


def trailer_net_book_value(trailer):
    ttype = store.trailer_types.get(trailer["trailer_type_id"])
    floor_cents = (ttype or {}).get("residual_floor_cents") or 0
    in_service = store.parse_date(trailer.get("in_service_date"))
    cost = trailer.get("acquisition_cost_cents") or 0
    if in_service is None:
        return max(floor_cents, cost)
    days = (store.clock_date() - in_service).days
    months = floor_div(days, DEPRECIATION_MONTH_DAYS)
    depreciation = round_half_up(dec(cost) * DEPRECIATION_RATE_PER_YEAR * dec(months) / dec(12))
    return max(floor_cents, cost - depreciation)


# --- branch counters -------------------------------------------------------
def branch_on_hand_count(branch_id):
    n = 0
    for t in store.trailers.values():
        if t.get("current_branch_id") == branch_id and t.get("availability_status") in ("AVAILABLE", "ALLOCATED"):
            n += 1
    return n


def branch_serviceable_available_count(branch_id, trailer_type_id=None):
    n = 0
    for t in store.trailers.values():
        if t.get("current_branch_id") != branch_id:
            continue
        if trailer_type_id is not None and t.get("trailer_type_id") != trailer_type_id:
            continue
        if t.get("availability_status") != "AVAILABLE":
            continue
        if trailer_service_status(t) != "SERVICEABLE":
            continue
        n += 1
    return n


# --- customer balance and risk --------------------------------------------
def outstanding_chargeback_cents(customer_id):
    total = 0
    for cb in store.chargebacks.values():
        if cb.get("customer_id") == customer_id and cb.get("status") in ("PENDING", "DISPUTED", "APPROVED"):
            total += cb.get("amount_cents") or 0
    return total


def _customer_assessments(customer_id):
    out = []
    for a in store.damage_assessments.values():
        unit = store.agreement_units.get(a.get("agreement_unit_id"))
        if unit is None:
            continue
        agreement = store.agreements.get(unit.get("agreement_id"))
        if agreement is None or agreement.get("customer_id") != customer_id:
            continue
        out.append(a)
    return out


def customer_risk_score(customer, variant):
    base = BASE_BY_TIER.get(customer.get("credit_tier"), 0)
    cb_sum = 0
    if variant == "underwriting_snapshot":
        for cb in store.chargebacks.values():
            if cb.get("customer_id") == customer["id"] and cb.get("status") in ("APPROVED", "SETTLED"):
                cb_sum += cb.get("amount_cents") or 0
        n_assess = len([a for a in _customer_assessments(customer["id"]) if a.get("status") == "APPROVED"])
    else:
        today = store.clock_date()
        for cb in store.chargebacks.values():
            if cb.get("customer_id") != customer["id"]:
                continue
            if cb.get("status") not in ("PENDING", "DISPUTED", "APPROVED", "SETTLED"):
                continue
            amount = cb.get("amount_cents") or 0
            created = store.parse_datetime(cb.get("created_at"))
            age_days = (today - created.date()).days if created else 0
            cb_sum += (amount // 2) if age_days > DECAY_AGE_DAYS else amount
        n_assess = len([a for a in _customer_assessments(customer["id"])
                        if a.get("status") in ("SUBMITTED", "APPROVED")])

    chargeback_points = floor_div(cb_sum, 10000) * CHARGEBACK_POINTS_PER_10000_CENTS
    assessment_points = n_assess * ASSESSMENT_POINTS_EACH
    raw = base + chargeback_points + assessment_points
    score = min(SCORE_CAP, max(SCORE_FLOOR, raw))
    return {
        "base_points": base,
        "chargeback_weight_points": chargeback_points,
        "assessment_points": assessment_points,
        "weighted_chargeback_cents": cb_sum,
        "risk_score": score,
    }


# --- pricing ---------------------------------------------------------------
def peak_day_count(branch, start, end):
    """Days d in the half-open [start, end) inside the closed branch peak window."""
    peak_start = store.parse_date(branch.get("peak_season_start_date"))
    peak_end = store.parse_date(branch.get("peak_season_end_date"))
    if peak_start is None or peak_end is None or start is None or end is None:
        return 0
    lo = max(start, peak_start)
    hi = min(end - timedelta(days=1), peak_end)
    if hi < lo:
        return 0
    return (hi - lo).days + 1


def peak_daily_rate(card):
    return dec(card["daily_rate_cents"]) * (Decimal("1") + dec(card.get("peak_uplift_pct") or 0))


def quoted_total_cents(agreement, card, branch):
    start = store.parse_date(agreement["start_date"])
    end = store.parse_date(agreement["end_date"])
    term_days = (end - start).days
    pk = peak_day_count(branch, start, end)
    off = term_days - pk
    per_unit = round_half_up(dec(card["daily_rate_cents"]) * dec(off) + peak_daily_rate(card) * dec(pk))
    return per_unit * agreement["unit_count"]


def line_charge(unit, agreement, card, branch):
    """Returns (peak_days, excess_miles, drop_charge_cents, line_charge_cents)."""
    checkout = store.parse_date(unit["checkout_date"])
    returned = store.parse_date(unit["return_date"])
    days_out = (returned - checkout).days
    pk = peak_day_count(branch, checkout, returned)
    off_days = days_out - pk
    base = dec(card["daily_rate_cents"]) * dec(off_days) + peak_daily_rate(card) * dec(pk)
    included = floor_div((card.get("mileage_included_per_month") or 0) * days_out, MILEAGE_PRORATION_DAYS)
    run = (unit.get("return_hub_miles") or 0) - (unit.get("checkout_hub_miles") or 0)
    excess = max(0, run - included)
    mileage_charge = excess * (card.get("excess_mileage_rate_cents_per_mile") or 0)
    drop = DROP_CHARGE_CENTS if unit.get("return_branch_id") != agreement.get("branch_id") else 0
    charge = round_half_up(base + dec(mileage_charge) + dec(drop))
    return pk, excess, drop, charge


def purchase_option_price(final_total, trailer, ttype):
    cumulative_paid = final_total or 0
    uncapped_credit = round_half_up(dec(cumulative_paid) * LEASE_CREDIT_RATE)
    base_price = max(trailer_net_book_value(trailer), ttype.get("residual_floor_cents") or 0)
    credit_cap = floor_dec(dec(base_price) * MAX_CREDIT_PCT)
    applied_credit = min(uncapped_credit, credit_cap)
    return max(base_price - applied_credit, ttype.get("residual_floor_cents") or 0)


# --- damage liability ------------------------------------------------------
def damage_liability(line_items, customer, certificate):
    assessed = 0
    points = 0
    for item in line_items:
        mult = SEVERITY_MULTIPLIER[item["severity"]]
        assessed += round_half_up(dec(item["quantity"]) * dec(item["unit_cost_cents"]) * mult)
        points += SEVERITY_POINTS[item["severity"]] * item["quantity"]
    deductible = DEDUCTIBLE_BY_TIER.get(customer.get("credit_tier"), 0)
    limit = 0
    if certificate is not None:
        limit = certificate.get("physical_damage_limit_cents") or 0
    insured = min(max(assessed - deductible, 0), limit)
    customer_liable = assessed - insured
    admin_fee = round_half_up(dec(customer_liable) * ADMIN_FEE_PCT)
    return {
        "assessed_amount_cents": assessed,
        "damage_points": points,
        "insured_portion_cents": insured,
        "customer_liable_cents": customer_liable,
        "admin_fee_cents": admin_fee,
        "chargeback_amount_cents": customer_liable + admin_fee,
    }


# --- relocation cost -------------------------------------------------------
def band_cost(miles):
    return (BAND1_RATE_CENTS_PER_MILE * min(miles, BAND1_MAX_MILES)
            + BAND2_RATE_CENTS_PER_MILE * max(0, min(miles, BAND2_MAX_MILES) - BAND1_MAX_MILES)
            + BAND3_RATE_CENTS_PER_MILE * max(0, miles - BAND2_MAX_MILES))


def relocation_cost_cents(miles, deadhead):
    miles = miles or 0
    deadhead = deadhead or 0
    subtotal = BASE_DISPATCH_FEE_CENTS + band_cost(miles) + deadhead * DEADHEAD_RATE_CENTS_PER_MILE
    surcharge = 0
    if (miles + deadhead) > FUEL_SURCHARGE_MILE_THRESHOLD:
        surcharge = round_half_up(dec(subtotal) * FUEL_SURCHARGE_PCT)
    return max(MIN_CHARGE_CENTS, subtotal + surcharge)


# --- interval helpers ------------------------------------------------------
def half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def inbound_window(order):
    arrive = store.parse_date(order.get("planned_arrive_date"))
    if arrive is None:
        return None, None
    return (store.add_days(arrive, -INBOUND_BUFFER_DAYS_BEFORE),
            store.add_days(arrive, BRANCH_DWELL_DAYS_AFTER))
