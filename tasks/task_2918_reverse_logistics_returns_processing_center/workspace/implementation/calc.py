"""Every pinned calculation. All money is integer cents; all rounding is half away
from zero (ROUND_HALF_UP in Python's decimal module)."""

from decimal import Decimal, ROUND_HALF_UP

import constants as K

ONE = Decimal(1)


def rhu(value):
    """Round a Decimal half away from zero to a whole cent (integer)."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(ONE, rounding=ROUND_HALF_UP))


def rhu_places(value, places):
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(ONE.scaleb(-places), rounding=ROUND_HALF_UP)


def pct2(value):
    return rhu_places(value, 2)


def pct4(value):
    return rhu_places(value, 4)


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# ------------------------------------------------------- receipt weight profile

def expected_weight_grams(rma_lines, item_lookup):
    total = K.TARE_WEIGHT_GRAMS
    for line in rma_lines:
        item = item_lookup(line["catalog_item_id"])
        if item is None:
            continue
        total += item["unit_weight_grams"] * line["authorized_quantity"]
    return total


def empty_box_suspected(gross_weight_grams, expected_weight_grams_value):
    return (gross_weight_grams * K.EMPTY_BOX_THRESHOLD_DEN) < (
        expected_weight_grams_value * K.EMPTY_BOX_THRESHOLD_NUM
    )


def days_since_order(order_placed_at, received_at):
    seconds = int((received_at - order_placed_at).total_seconds())
    return seconds // 86400


# --------------------------------------------------------- provisional recovery

def provisional_unit_recovery(declared_value_cents, grade, reason_code):
    multiplier = K.GRADE_VALUE_MULTIPLIER[grade]
    penalty = K.REASON_PENALTY_PCT[reason_code]
    return rhu(Decimal(declared_value_cents) * multiplier * (ONE - penalty))


def provisional_recovery(declared_value_cents, grade, reason_code, quantity):
    return provisional_unit_recovery(declared_value_cents, grade, reason_code) * quantity


# ------------------------------------------------------------- refund economics

def late_return_adjustment(days):
    if days is None:
        return Decimal("0.00")
    if days > K.LATE_TIER_HIGH_DAYS:
        return K.LATE_ADJ_HIGH
    if days > K.LATE_TIER_LOW_DAYS:
        return K.LATE_ADJ_LOW
    return Decimal("0.00")


def restocking_fee_pct(reason_code, service_level, grade, days):
    base = K.REASON_BASE_FEE_PCT[reason_code]
    service = K.SERVICE_LEVEL_FEE_ADJ[service_level]
    grade_adj = K.GRADE_FEE_ADJ[grade]
    late = late_return_adjustment(days)
    raw = base + service + grade_adj + late
    return pct2(clamp(raw, K.RESTOCKING_FEE_MIN, K.RESTOCKING_FEE_MAX))


def refund_amounts(declared_value_cents, quantity, fee_pct):
    gross = declared_value_cents * quantity
    fee = rhu(Decimal(gross) * fee_pct)
    return gross, fee, gross - fee


# ---------------------------------------------------------------- fraud scoring

def fraud_points(check_type, outcome):
    return K.FRAUD_WEIGHTS[check_type] if outcome == "FAIL" else 0


def score(checks, stages):
    total = 0
    for check in checks:
        if check["evaluated_stage"] in stages:
            total += check["weight_points"]
    return total


# ------------------------------------------------------------ disposition logic

def projected_refurb_margin(declared_value_cents):
    return rhu(Decimal(declared_value_cents) * K.REFURB_MARGIN_GRADE_MULT) - (
        K.REFURB_STANDARD_COST_CENTS
    )


def liquidation_floor_scaled(liquidation_floor_pct):
    return rhu(Decimal(liquidation_floor_pct) * 100)


def decide_disposition(client, item, grade, quantity, recovery_value_cents, refurb_available):
    """The D1..D8 decision matrix, evaluated top to bottom; the first match wins."""
    hazard = item["hazard_class"]
    recall = item["recall_status"]
    declared = item["declared_value_cents"]

    # D1 — a mandatory recall overrides everything.
    if recall == "MANDATORY":
        return "DESTROY"
    # D2 — hazardous goods in poor condition are destroyed.
    if hazard != "NONE" and grade in ("C", "D", "SCRAP"):
        return "DESTROY"
    # D3 — scrap is destroyed.
    if grade == "SCRAP":
        return "DESTROY"
    # D4 — good enough for the shelf.
    if (
        K.GRADE_RANK[grade] <= K.GRADE_RANK[client["restock_grade_floor"]]
        and hazard == "NONE"
        and recall == "NONE"
    ):
        return "RESTOCK"
    # D5 — worth refurbishing.
    if (
        refurb_available
        and grade in ("B", "C")
        and hazard == "NONE"
        and projected_refurb_margin(declared) > 0
    ):
        return "REFURBISH"
    # D6 — clears the liquidation floor.
    if recovery_value_cents * 100 >= (
        declared * quantity * liquidation_floor_scaled(client["liquidation_floor_pct"])
    ):
        return "LIQUIDATE"
    # D7 — donatable.
    if client["donation_allowed"] and grade != "SCRAP" and not item["regulated_flag"]:
        return "DONATE"
    # D8 — otherwise destroy.
    return "DESTROY"


# ------------------------------------------------------------- refurbishment cost

def refurb_total_cost(labor_minutes_total, parts_cost_cents, packaging_cost_cents):
    direct = (
        labor_minutes_total * K.REFURB_LABOR_RATE_CENTS_PER_MIN
        + parts_cost_cents
        + packaging_cost_cents
    )
    return rhu(Decimal(direct) * K.REFURB_OVERHEAD_MULTIPLIER)


# --------------------------------------------------------- channel lot economics

def unit_price_cents(disposition, recovery_value_cents, quantity, channel, item):
    if disposition == "RESTOCK":
        return rhu(Decimal(recovery_value_cents) / Decimal(quantity))
    if disposition in ("DONATE", "DESTROY"):
        return 0
    per_unit = Decimal(recovery_value_cents) / Decimal(quantity)
    indexed = rhu(per_unit * channel["price_index_pct"])
    floor = item["secondary_market_floor_cents"]
    return floor if floor > indexed else indexed


def lot_band_surcharge(gross_lot_value_cents):
    if gross_lot_value_cents < K.LOT_SMALL_CEILING:
        return K.LOT_SMALL_SURCHARGE
    if gross_lot_value_cents < K.LOT_LARGE_FLOOR:
        return K.LOT_MID_SURCHARGE
    return K.LOT_LARGE_SURCHARGE


def effective_fee_pct(channel_fee_pct, gross_lot_value_cents):
    raw = channel_fee_pct + lot_band_surcharge(gross_lot_value_cents)
    return pct2(clamp(raw, K.FEE_PCT_MIN, K.FEE_PCT_MAX))


def lot_economics(channel, unit_price, quantity, refurb_cost_cents):
    """The pinned five-step realized-economics sequence."""
    gross = unit_price * quantity
    if channel is None:
        fee_pct = Decimal("0.00")
        fee = 0
    else:
        fee_pct = effective_fee_pct(channel["fee_pct"], gross)
        fee = rhu(Decimal(gross) * fee_pct)
    net = gross - fee - refurb_cost_cents
    return gross, fee_pct, fee, net


def projected_net_recovery(channel, unit_price, quantity):
    gross, _fee_pct, fee, _net = lot_economics(channel, unit_price, quantity, 0)
    return gross - fee


# ------------------------------------------------------------------ ledger maths

def recovery_credit_amount(net_recovery_cents):
    return net_recovery_cents - rhu(Decimal(net_recovery_cents) * K.HANDLING_SHARE_PCT)


def donation_write_off_amount(declared_value_cents, quantity):
    return -(declared_value_cents * quantity)


def destruction_write_off_amount(declared_value_cents, quantity):
    return -((declared_value_cents + K.DESTRUCTION_FEE_CENTS_PER_UNIT) * quantity)


def receipt_variance_amount(authorized_quantity, received_quantity, declared_value_cents):
    return -((authorized_quantity - received_quantity) * declared_value_cents)


# ------------------------------------------------------------- pricing feedback

def variance_pct(realized_price_cents, expected_price_cents):
    if expected_price_cents == 0:
        return Decimal("0.0000")
    delta = Decimal(realized_price_cents - expected_price_cents)
    return pct4(delta / Decimal(expected_price_cents))


def feedback_ratio(realized_price_cents, expected_price_cents):
    if expected_price_cents == 0:
        return 10000
    return rhu(Decimal(realized_price_cents * 10000) / Decimal(expected_price_cents))


def price_index_from_ratios(ratios):
    if not ratios:
        return None
    mean = rhu(Decimal(sum(ratios)) / Decimal(len(ratios)))
    raw = pct4(Decimal(mean) / Decimal(10000))
    return clamp(raw, K.PRICE_INDEX_MIN, K.PRICE_INDEX_MAX)
