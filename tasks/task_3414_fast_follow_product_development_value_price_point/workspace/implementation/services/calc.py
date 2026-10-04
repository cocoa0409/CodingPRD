"""Calculation rules (scaffold 1.3). Pure computations only; mutations and
cascades live in services/cascade.py.

Money is integer cents; fractional results are rounded half up per component
before summation (PRD 2.6). Amortization divisions round up (ceil). All
multiplicative math runs through Decimal built from str() of the JSON number
so binary float error never leaks into a rounded cent.
"""
import math
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from core import clock
from core.constants import (
    COST_RATIO_T1,
    COST_RATIO_T1_MAX,
    COST_RATIO_T2,
    COST_RATIO_T2_MAX,
    COST_RATIO_T3,
    COST_RATIO_T3_MAX,
    COST_RATIO_T4,
    FACINGS_WEEKLY_SELLTROUGH,
    GROWTH_CAP,
    LAUNCH_WEEKS,
    MARKDOWN_DEPTH_T1,
    MARKDOWN_DEPTH_T2,
    MARKDOWN_DEPTH_T3,
    MARKDOWN_DEPTH_T4,
    MARKDOWN_RISK_CAP,
    MARKDOWN_TIER1_MAX_WEEKS,
    MARKDOWN_TIER2_MAX_WEEKS,
    MARKDOWN_TIER3_MAX_WEEKS,
    SAMPLE_CAP_PCT,
    SOURCE_PRESTIGE_LAUNCH,
    TOOLING_NEW_WEEKS,
    TOOLING_REUSE_WEEKS,
    TREND_DECAY_PCT_PER_WEEK,
    VELOCITY_CAP_PER_DAY,
    W_GROWTH,
    W_SIGNAL,
    W_VELOCITY,
)
from core.errors import err

D = lambda x: Decimal(str(x))  # noqa: E731

_CENT = Decimal("1")
_TENTH = Decimal("0.1")
_HUNDREDTH = Decimal("0.01")


def _round_half_up_int(dec):
    return int(dec.quantize(_CENT, rounding=ROUND_HALF_UP))


def _ceil_div(a, b):
    return int((D(a) / D(b)).quantize(_CENT, rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# trend_momentum_score: on every entry into EVALUATING
# ---------------------------------------------------------------------------
def momentum_score(trend):
    velocity_norm = min(D(trend["mention_velocity_7d"]) / D(VELOCITY_CAP_PER_DAY), D(1))
    growth_norm = min(D(trend["engagement_growth_pct"]) / GROWTH_CAP, D(1))
    if trend["source"] == SOURCE_PRESTIGE_LAUNCH:
        signal_norm = D(trend["prestige_similarity"])
    else:
        signal_norm = D(trend["cross_platform_spread"])
    score = (
        W_VELOCITY * velocity_norm * 100
        + W_GROWTH * growth_norm * 100
        + W_SIGNAL * signal_norm * 100
    ).quantize(_TENTH, rounding=ROUND_HALF_UP)
    return float(score)


# ---------------------------------------------------------------------------
# target_unit_cost: Concept PITCHED -> SELECTED (integer cents, floor)
# ---------------------------------------------------------------------------
def target_unit_cost(price_point_cents):
    if price_point_cents <= COST_RATIO_T1_MAX:
        ratio = COST_RATIO_T1
    elif price_point_cents <= COST_RATIO_T2_MAX:
        ratio = COST_RATIO_T2
    elif price_point_cents <= COST_RATIO_T3_MAX:
        ratio = COST_RATIO_T3
    else:
        ratio = COST_RATIO_T4
    return int((D(price_point_cents) * ratio).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# landed_unit_cost: pinned rounding order — round per component, then sum.
# ---------------------------------------------------------------------------
def freight_per_unit(freight_total_cents, unit_weight_grams, shipment_weight_grams):
    return _round_half_up_int(
        D(freight_total_cents) * D(unit_weight_grams) / D(shipment_weight_grams)
    )


def duty_per_unit(unit_cost_cents, freight_per_unit_cents, duty_rate):
    # duty derives from the ALREADY-ROUNDED freight component
    return _round_half_up_int((D(unit_cost_cents) + D(freight_per_unit_cents)) * D(duty_rate))


def landed_unit_cost(unit_cost_cents, tooling_fee_cents, qty, freight_pu, duty_pu):
    """landed(q) = unit cost + ceil(tooling/q) + freight per unit + duty per unit."""
    return (
        unit_cost_cents
        + _ceil_div(tooling_fee_cents, qty)
        + freight_pu
        + duty_pu
    )


def provisional_landed(quote_fields):
    fpu = freight_per_unit(
        quote_fields["freight_total_cents"],
        quote_fields["unit_weight_grams"],
        quote_fields["shipment_weight_grams"],
    )
    dpu = duty_per_unit(quote_fields["unit_cost_cents"], fpu, quote_fields["duty_rate"])
    total = landed_unit_cost(
        quote_fields["unit_cost_cents"],
        quote_fields["tooling_fee_cents"],
        quote_fields["initial_order_qty"],
        fpu,
        dpu,
    )
    return total, fpu, dpu


def settled_landed(quote, actual_qty, actual_freight_total_cents):
    fpu = freight_per_unit(
        actual_freight_total_cents,
        quote["unit_weight_grams"],
        quote["shipment_weight_grams"],
    )
    dpu = duty_per_unit(quote["unit_cost_cents"], fpu, quote["duty_rate"])
    return landed_unit_cost(
        quote["unit_cost_cents"], quote["tooling_fee_cents"], actual_qty, fpu, dpu
    )


# ---------------------------------------------------------------------------
# packaging_lead_time: tooling reuse detection at Product creation
# ---------------------------------------------------------------------------
def detect_tooling_reuse(tooling_code, created_at, all_products):
    """True iff a tooling_code was supplied and another product exists with the
    same code, a strictly earlier created_at, and status != KILLED."""
    if not tooling_code:
        return False
    for other in all_products:
        if other["tooling_code"] != tooling_code:
            continue
        if other["status"] == "KILLED":
            continue
        if other["created_at"] < created_at:
            return True
    return False


def packaging_lead_weeks(tooling_reuse):
    return TOOLING_REUSE_WEEKS if tooling_reuse else TOOLING_NEW_WEEKS


# ---------------------------------------------------------------------------
# markdown_risk: at LaunchPlan creation (ratio, 2 decimal places)
# ---------------------------------------------------------------------------
def _whole_weeks(earlier, later):
    delta_seconds = (later - earlier).total_seconds()
    return math.floor(delta_seconds / (7 * 86400))


def markdown_risk_pct(trend_created_at, plan_created_at):
    weeks = _whole_weeks(trend_created_at, plan_created_at)
    risk = min(D(weeks) * TREND_DECAY_PCT_PER_WEEK, MARKDOWN_RISK_CAP)
    return float(risk.quantize(_HUNDREDTH, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# launch_quantity: variants at creation + single-pass lock
# ---------------------------------------------------------------------------
def capacity_units(facings):
    return facings * FACINGS_WEEKLY_SELLTROUGH * LAUNCH_WEEKS


def qty_variants(demand_forecast_units, cap_units, risk_pct):
    demand_variant = min(demand_forecast_units, cap_units)
    risk_qty = math.floor(D(demand_forecast_units) * (D(1) - D(risk_pct)))
    risk_variant = min(risk_qty, cap_units)
    return demand_variant, risk_variant


def lock_quantity(q0, cogs_budget_cents, moq, landed_at):
    """Single-pass lock (no fixed-point iteration). landed_at(q) evaluates the
    landed unit cost at quantity q. Returns (qty_locked_units,
    landed_locked_cents) or raises ERR_BUDGET_EXCEEDED / ERR_BELOW_MOQ."""
    if q0 <= 0:
        # A zero candidate can never meet a MOQ of at least 1.
        raise err(
            "ERR_BELOW_MOQ",
            "locked quantity 0 is below the manufacturer minimum order quantity",
        )
    if q0 * landed_at(q0) > cogs_budget_cents:
        q1 = cogs_budget_cents // landed_at(moq)
        if q1 < moq:
            raise err(
                "ERR_BUDGET_EXCEEDED",
                "budget clamp falls below the manufacturer minimum order quantity",
            )
        qty = q1
    else:
        qty = q0
    if qty < moq:
        raise err(
            "ERR_BELOW_MOQ",
            "locked quantity is below the manufacturer minimum order quantity",
        )
    return qty, landed_at(qty)


# ---------------------------------------------------------------------------
# markdown_exposure: at LaunchPlan EXECUTED -> RECONCILED
# ---------------------------------------------------------------------------
def markdown_depth_weeks(launched_at, now):
    return _whole_weeks(launched_at, now)


def markdown_exposure_cents(markdown_units, landed_locked_cents, launched_at, now):
    weeks = markdown_depth_weeks(launched_at, now)
    if weeks <= MARKDOWN_TIER1_MAX_WEEKS:
        depth = MARKDOWN_DEPTH_T1
    elif weeks <= MARKDOWN_TIER2_MAX_WEEKS:
        depth = MARKDOWN_DEPTH_T2
    elif weeks <= MARKDOWN_TIER3_MAX_WEEKS:
        depth = MARKDOWN_DEPTH_T3
    else:
        depth = MARKDOWN_DEPTH_T4
    return _round_half_up_int(D(markdown_units) * D(landed_locked_cents) * depth)


# ---------------------------------------------------------------------------
# shelf_capacity_reconciliation: committed / available facings per category
# ---------------------------------------------------------------------------
def facing_maps(partner_id, category_capacities, line_reviews, planogram_slots):
    review_partner = {r["id"]: r["retail_partner_id"] for r in line_reviews}
    committed = {}
    for slot in planogram_slots:
        if slot["status"] not in ("COMMITTED", "ACTIVE"):
            continue
        if review_partner.get(slot["line_review_id"]) != partner_id:
            continue
        committed[slot["category"]] = committed.get(slot["category"], 0) + slot["facings"]
    committed_out = {}
    available_out = {}
    for category, capacity in category_capacities.items():
        used = committed.get(category, 0)
        committed_out[category] = used
        available_out[category] = max(0, capacity - used)
    for category, used in committed.items():
        if category not in committed_out:
            committed_out[category] = used
    return committed_out, available_out


# ---------------------------------------------------------------------------
# sampling_burn helpers
# ---------------------------------------------------------------------------
def sample_cap(qty_locked_units):
    return math.floor(D(qty_locked_units) * SAMPLE_CAP_PCT)


def cm_accepted_count(manufacturer_id, production_quarter, cost_quotes):
    """cm_quarterly_capacity: quotes consume slots in accepted_at ASC order
    (created_at ASC tie-break); consumption is the count of ACCEPTED quotes."""
    return sum(
        1
        for q in cost_quotes
        if q["contract_manufacturer_id"] == manufacturer_id
        and q["production_quarter"] == production_quarter
        and q["status"] == "ACCEPTED"
    )


def now():
    return clock.now()
