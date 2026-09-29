"""The thirteen calculation rules of PRD section 3 - pure arithmetic only.

Every monetary or fractional figure is computed with decimal.Decimal and
half-up rounding. Python's float arithmetic and built-in round() are never
used for a business figure.
"""
from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------------ constants
INTENSITY_PENALTY_PER_KG = Decimal("4.0")
PENALTY_CAP = Decimal("60.0")
COMPLIANCE_WEIGHT = Decimal("25.0")
PRE_CONSUMER_BONUS = Decimal("3.0")
PRE_CONSUMER_BONUS_THRESHOLD = Decimal("0.60")

COACHING_INTENSITY_THRESHOLD = Decimal("12.000")
HIGH_SEVERITY_INTENSITY = Decimal("18.000")
OVERPRODUCTION_SPIKE_GRAMS = 5000

ESCALATION_ALERT_COUNT = 3
STATION_TURNAROUND_SECONDS = 60

SURCHARGE_TIER_1_CENTS = 5000
SURCHARGE_TIER_2_CENTS = 15000
VARIANCE_TOLERANCE_PCT = Decimal("5.00")
VARIANCE_CREDIT_RATE = Decimal("0.10")

DUPLICATE_WINDOW_SECONDS = 300
OUTLIER_GRAMS_THRESHOLD = 25000

DEFAULT_TARGET_INTENSITY = Decimal("10.000")


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to the given number of decimal places."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


# ------------------------------------------------------- recipe_cost_per_kg
def recipe_cost(ingredients):
    """Per-line rounding, then integer sum; usable yield rounded to 3 dp."""
    total_cost = 0
    usable = Decimal("0")
    for item in ingredients:
        quantity = D(item["quantity_kg"])
        unit_cost = D(item["unit_cost_cents_per_kg"])
        trim = D(item["trim_loss_pct"])
        total_cost += rhu_int(quantity * unit_cost)
        usable += quantity * (Decimal("1") - trim)
    usable_yield_kg = rhu(usable, 3)
    if usable_yield_kg == 0:
        cost_per_kg = None
    else:
        cost_per_kg = rhu_int(D(total_cost) / usable_yield_kg)
    return total_cost, usable_yield_kg, cost_per_kg


# ---------------------------------------------------- waste_entry_valuation
def valuation_cost(weight_grams, basis_cents_per_kg):
    """round_half_up(weight_grams / 1000 * basis, 0) - grams/kg kept exact."""
    if basis_cents_per_kg is None:
        return None
    kilograms = D(weight_grams) / Decimal("1000")
    return rhu_int(kilograms * D(basis_cents_per_kg))


# ------------------------------------------------- entry_stream_segmentation
def entry_stream(station_kind, loss_reason):
    if station_kind == "DISH_RETURN" or loss_reason == "PLATE_WASTE":
        return "POST_CONSUMER"
    return "PRE_CONSUMER"


# ------------------------------------------------------ shift_waste_intensity
def intensity_per_1k_meals(waste_grams, meals_served):
    """grams / meals rounded to 3 dp; null when no meals were served."""
    if not meals_served:
        return None
    return rhu(D(waste_grams) / D(meals_served), 3)


def pre_consumer_share(pre_consumer_grams, total_grams):
    if not total_grams:
        return None
    return rhu(D(pre_consumer_grams) / D(total_grams), 4)


def capture_compliance(stations_with_capture, active_station_count):
    if not active_station_count:
        return Decimal("1.0000")
    return rhu(D(stations_with_capture) / D(active_station_count), 4)


# ----------------------------------------------------- shift_leaderboard_score
def leaderboard_score(intensity, target_intensity, compliance_pct, pre_share):
    excess = Decimal("0")
    if intensity is not None:
        diff = D(intensity) - D(target_intensity)
        if diff > 0:
            excess = diff
    penalty = excess * INTENSITY_PENALTY_PER_KG
    if penalty > PENALTY_CAP:
        penalty = PENALTY_CAP
    compliance_penalty = (Decimal("1") - D(compliance_pct)) * COMPLIANCE_WEIGHT
    bonus = Decimal("0")
    if pre_share is not None and D(pre_share) >= PRE_CONSUMER_BONUS_THRESHOLD:
        bonus = PRE_CONSUMER_BONUS
    raw = Decimal("100") - penalty - compliance_penalty + bonus
    if raw < 0:
        raw = Decimal("0")
    if raw > 100:
        raw = Decimal("100")
    return rhu(raw, 1)


# ------------------------------------------------------- site_waste_aggregates
def diversion_rate(diverted_grams, captured_grams):
    if not captured_grams:
        return None
    return rhu(D(diverted_grams) / D(captured_grams) * Decimal("100"), 2)


def coaching_posture(open_alert_count):
    if open_alert_count == 0:
        return "MONITORING"
    if open_alert_count >= ESCALATION_ALERT_COUNT:
        return "ESCALATED"
    return "INTERVENTION"


# -------------------------------------------------------- reduction_attainment
def reduction_pct(baseline_value, performance_value):
    """(baseline - performance) / baseline * 100 rounded to 2 dp."""
    if baseline_value is None or performance_value is None:
        return None
    baseline = D(baseline_value)
    if baseline == 0:
        return None
    return rhu((baseline - D(performance_value)) / baseline * Decimal("100"), 2)


# ---------------------------------------------------- hauler_ticket_settlement
def settlement_figures(gross_weight_grams, container_tare_grams,
                       rate_cents_per_tonne, stop_fee_cents, staged_weight_grams):
    net = gross_weight_grams - container_tare_grams
    billable_tonnes = rhu(D(net) / Decimal("1000000"), 4)
    base = rhu_int(billable_tonnes * D(rate_cents_per_tonne)) + stop_fee_cents
    if base < SURCHARGE_TIER_1_CENTS:
        pct = Decimal("0.00")
    elif base < SURCHARGE_TIER_2_CENTS:
        pct = Decimal("0.06")
    else:
        pct = Decimal("0.09")
    surcharge = rhu_int(D(base) * pct)
    subtotal = base + surcharge
    if staged_weight_grams:
        variance = rhu(abs(D(net) - D(staged_weight_grams)) / D(staged_weight_grams)
                       * Decimal("100"), 2)
    else:
        variance = Decimal("0.00")
    if variance > VARIANCE_TOLERANCE_PCT:
        credit = rhu_int(D(subtotal) * VARIANCE_CREDIT_RATE)
    else:
        credit = 0
    total = subtotal - credit
    return {
        "net_weight_grams": net,
        "billable_tonnes": billable_tonnes,
        "base_haul_fee_cents": base,
        "fuel_surcharge_pct": pct,
        "fuel_surcharge_cents": surcharge,
        "settlement_subtotal_cents": subtotal,
        "variance_pct": variance,
        "variance_credit_cents": credit,
        "settlement_total_cents": total,
    }
