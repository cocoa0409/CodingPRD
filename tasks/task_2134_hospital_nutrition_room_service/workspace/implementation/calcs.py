"""The ten calculation rules of the PRD, with their pinned evaluation orders.

All money and all rounded quantities go through decimal arithmetic; the
rounding method is round half up everywhere (PRD section 2.9).
"""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# --- ordinal scales --------------------------------------------------------
TEXTURE_LEVELS = ["REGULAR", "MINCED_MOIST", "PUREED", "LIQUIDISED"]
LIQUID_LEVELS = ["THIN", "MILDLY_THICK", "MODERATELY_THICK", "EXTREMELY_THICK"]
TEXTURE_ORDINAL = {name: i for i, name in enumerate(TEXTURE_LEVELS)}
LIQUID_ORDINAL = {name: i for i, name in enumerate(LIQUID_LEVELS)}

# --- constants -------------------------------------------------------------
CLEAR_LIQUID_CARB_CAP_G = Decimal("15.0")
WASTE_FACTOR = Decimal("1.08")
TEXTURE_PREP_SURCHARGE_CENTS = {
    "REGULAR": 0,
    "MINCED_MOIST": 25,
    "PUREED": 60,
    "LIQUIDISED": 90,
}
TIER_A_MAX_EXCLUSIVE = 2000
TIER_B_MAX_EXCLUSIVE = 6000
OVERHEAD_RATE = {"A": Decimal("0.180"), "B": Decimal("0.150"), "C": Decimal("0.120")}
BULK_DISCOUNT_RATE = {"A": Decimal("0.000"), "B": Decimal("0.020"), "C": Decimal("0.045")}
ROLLING_HISTORY_DEPTH = 3
NO_SHOW_ADJUSTMENT = Decimal("0.92")
PARTICIPATION_RATE = Decimal("0.85")
AVERAGE_TRAY_COST_CENTS = 1150
HOT_MIN_CELSIUS = Decimal("60.0")
COLD_MAX_CELSIUS = Decimal("4.0")
LATE_PENALTY = 25
EARLY_PENALTY = 10
TEMP_RETRY_PENALTY = 15
ACCURACY_RETRY_PENALTY = 20
RISK_TIER_MODERATE_MIN = Decimal("30")
RISK_TIER_HIGH_MIN = Decimal("60")
SCREENING_WEIGHTS = {"weight_loss": Decimal("0.50"), "intake": Decimal("0.30"),
                     "bmi": Decimal("0.20")}
COMPREHENSIVE_WEIGHTS = {"weight_loss": Decimal("0.35"), "intake": Decimal("0.25"),
                         "bmi": Decimal("0.20"), "albumin": Decimal("0.20")}
TASTE_WEIGHT = Decimal("0.40")
TEMPERATURE_WEIGHT = Decimal("0.35")
ACCURACY_WEIGHT = Decimal("0.25")
MISSED_MEAL_CONSULT_THRESHOLD = 2
CONSULT_URGENT_SLA_HOURS = 4
CONSULT_ROUTINE_SLA_HOURS = 24
MAX_REVISION_ROUNDS = 3


# --- rounding helpers ------------------------------------------------------
def dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# 1. effective_diet_envelope
# ---------------------------------------------------------------------------
def effective_diet_envelope(diet_order, patient, rules):
    """Five pinned steps; the NPO override is applied LAST and is not monotonic."""
    # step 1 -- numeric ceilings: smallest non-null wins, all-null means uncapped
    sodium = [r["max_sodium_mg_per_meal"] for r in rules
              if r["max_sodium_mg_per_meal"] is not None]
    potassium = [r["max_potassium_mg_per_meal"] for r in rules
                 if r["max_potassium_mg_per_meal"] is not None]
    carb = [r["max_carb_g_per_meal"] for r in rules
            if r["max_carb_g_per_meal"] is not None]
    sodium_cap = min(sodium) if sodium else None
    potassium_cap = min(potassium) if potassium else None
    carb_cap = rhu(min(carb), 1) if carb else None

    # step 2 -- texture floor: most restrictive across order, patient and rules
    texture_candidates = [diet_order["texture_level"], patient["texture_level"]]
    texture_candidates += [r["min_texture_level"] for r in rules
                           if r["min_texture_level"] is not None]
    texture = max(texture_candidates, key=lambda t: TEXTURE_ORDINAL[t])

    # step 3 -- thickness floor
    liquid_candidates = [diet_order["liquid_level"], patient["liquid_level"]]
    liquid_candidates += [r["min_liquid_level"] for r in rules
                          if r["min_liquid_level"] is not None]
    liquid = max(liquid_candidates, key=lambda l: LIQUID_ORDINAL[l])

    # step 4 -- nil-per-os override, applied last
    npo = patient["npo_status"]
    if npo == "NPO_STRICT":
        texture = "LIQUIDISED"
        sodium_cap = 0
        potassium_cap = 0
        carb_cap = Decimal("0.0")
    elif npo == "NPO_CLEAR_LIQUIDS":
        texture = "LIQUIDISED"
        liquid = "THIN"
        if carb_cap is None:
            carb_cap = CLEAR_LIQUID_CARB_CAP_G
        else:
            carb_cap = min(carb_cap, CLEAR_LIQUID_CARB_CAP_G)

    # step 5 -- forbidden tags: union, de-duplicated, ordered by rank then code
    owner_rank = {}
    for rule in rules:
        for tag in rule.get("forbidden_tag_codes") or []:
            rank = rule["precedence_rank"]
            if tag not in owner_rank or rank < owner_rank[tag]:
                owner_rank[tag] = rank
    tags = sorted(owner_rank.keys(), key=lambda t: (owner_rank[t], t))

    return {
        "effective_sodium_cap_mg": sodium_cap,
        "effective_potassium_cap_mg": potassium_cap,
        "effective_carb_cap_g": carb_cap,
        "effective_texture_level": texture,
        "effective_liquid_level": liquid,
        "forbidden_tag_codes_effective": tags,
    }


# ---------------------------------------------------------------------------
# 2. meal_order_nutrient_totals
# ---------------------------------------------------------------------------
def meal_order_nutrient_totals(lines, item_for):
    """lines already ordered created_at ASC; item_for(line) resolves the effective item."""
    sodium = 0
    potassium = 0
    carb = Decimal("0")
    protein = Decimal("0")
    hot = False
    cold = False
    for line in lines:
        item = item_for(line)
        qty = line["quantity"]
        sodium += item["sodium_mg"] * qty
        potassium += item["potassium_mg"] * qty
        carb += dec(item["carb_g"]) * qty
        protein += dec(item["protein_g"]) * qty
        if item["service_temp_class"] == "HOT":
            hot = True
        elif item["service_temp_class"] == "COLD":
            cold = True
    return {
        "total_sodium_mg": sodium,
        "total_potassium_mg": potassium,
        "total_carb_g": rhu(carb, 1),
        "total_protein_g": rhu(protein, 1),
        "requires_hot_probe": hot,
        "requires_cold_probe": cold,
    }


# ---------------------------------------------------------------------------
# 3. meal_order_food_cost -- rounded at the LINE, then summed
# ---------------------------------------------------------------------------
def meal_order_food_cost(lines, item_for, effective_texture_level):
    surcharge = TEXTURE_PREP_SURCHARGE_CENTS.get(effective_texture_level or "REGULAR", 0)
    line_costs = {}
    total = 0
    for line in lines:
        item = item_for(line)
        qty = line["quantity"]
        base_cents = item["unit_cost_cents"] * qty
        prep_cents = surcharge * qty
        cost = rhu_int((Decimal(base_cents) + Decimal(prep_cents)) * WASTE_FACTOR)
        line_costs[line["id"]] = cost
        total += cost
    return line_costs, total


# ---------------------------------------------------------------------------
# 4. meal_period_cost_rollup -- six pinned steps
# ---------------------------------------------------------------------------
def meal_period_cost_rollup(line_subtotal_cents):
    subtotal = int(line_subtotal_cents)
    if subtotal < TIER_A_MAX_EXCLUSIVE:
        tier = "A"
    elif subtotal < TIER_B_MAX_EXCLUSIVE:
        tier = "B"
    else:
        tier = "C"
    overhead = rhu_int(Decimal(subtotal) * OVERHEAD_RATE[tier])
    gross = subtotal + overhead
    discount = rhu_int(Decimal(gross) * BULK_DISCOUNT_RATE[tier])
    total = gross - discount
    return {
        "period_overhead_cents": overhead,
        "period_bulk_discount_cents": discount,
        "period_total_cost_cents": total,
    }


# ---------------------------------------------------------------------------
# 5. production_forecast_trays
# ---------------------------------------------------------------------------
def production_forecast_trays(variant, history, ward, census):
    if variant == "ROLLING_AVERAGE":
        if not history:
            trays = ward["tray_line_capacity_per_window"]
        else:
            total = sum(h["delivered_tray_count"] for h in history)
            mean = Decimal(total) / Decimal(len(history))
            trays = ceil_int(mean * NO_SHOW_ADJUSTMENT)
    else:  # CENSUS_BASED
        trays = ceil_int(Decimal(census) * PARTICIPATION_RATE)
    return trays, trays * AVERAGE_TRAY_COST_CENTS


# ---------------------------------------------------------------------------
# 6. forecast_variance
# ---------------------------------------------------------------------------
def forecast_variance(committed_tray_count, forecast_tray_count):
    if forecast_tray_count is None or forecast_tray_count == 0:
        return None
    value = (Decimal(committed_tray_count) - Decimal(forecast_tray_count)) \
        / Decimal(forecast_tray_count) * Decimal(100)
    return rhu(value, 2)


# ---------------------------------------------------------------------------
# 7. tray_service_compliance
# ---------------------------------------------------------------------------
def probes_satisfactory(order, hot_value, cold_value):
    hot_ok = (not order["requires_hot_probe"]) or (
        hot_value is not None and dec(hot_value) >= HOT_MIN_CELSIUS)
    cold_ok = (not order["requires_cold_probe"]) or (
        cold_value is not None and dec(cold_value) <= COLD_MAX_CELSIUS)
    return hot_ok and cold_ok


def delivery_window_compliance(delivered_at, window_start_at, window_end_at):
    if delivered_at < window_start_at:
        return "EARLY"
    if delivered_at >= window_end_at:
        return "LATE"
    return "ON_TIME"


def service_compliance_score(compliance, temperature_retry_count, accuracy_retry_count):
    score = 100
    if compliance == "LATE":
        score -= LATE_PENALTY
    elif compliance == "EARLY":
        score -= EARLY_PENALTY
    score -= TEMP_RETRY_PENALTY * temperature_retry_count
    score -= ACCURACY_RETRY_PENALTY * accuracy_retry_count
    return max(0, score)


# ---------------------------------------------------------------------------
# 8. malnutrition_risk_score
# ---------------------------------------------------------------------------
def _weight_loss_points(value):
    v = dec(value)
    if v < 5:
        return 0
    if v < 10:
        return 40
    if v < 15:
        return 70
    return 100


def _intake_points(value):
    v = dec(value)
    if v >= 75:
        return 0
    if v >= 50:
        return 40
    if v >= 25:
        return 70
    return 100


def _bmi_points(value):
    v = dec(value)
    if v >= 22:
        return 0
    if v >= Decimal("18.5"):
        return 40
    if v >= 16:
        return 70
    return 100


def _albumin_points(value):
    if value is None:
        return 0
    v = dec(value)
    if v >= Decimal("3.5"):
        return 0
    if v >= 3:
        return 40
    if v >= Decimal("2.5"):
        return 70
    return 100


def malnutrition_risk_score(variant, weight_loss_pct, intake_pct, bmi, albumin_g_dl):
    wl = Decimal(_weight_loss_points(weight_loss_pct))
    intake = Decimal(_intake_points(intake_pct))
    bmi_pts = Decimal(_bmi_points(bmi))
    if variant == "SCREENING":
        raw = (SCREENING_WEIGHTS["weight_loss"] * wl
               + SCREENING_WEIGHTS["intake"] * intake
               + SCREENING_WEIGHTS["bmi"] * bmi_pts)
    else:
        alb = Decimal(_albumin_points(albumin_g_dl))
        raw = (COMPREHENSIVE_WEIGHTS["weight_loss"] * wl
               + COMPREHENSIVE_WEIGHTS["intake"] * intake
               + COMPREHENSIVE_WEIGHTS["bmi"] * bmi_pts
               + COMPREHENSIVE_WEIGHTS["albumin"] * alb)
    score = rhu(raw, 2)
    if score < RISK_TIER_MODERATE_MIN:
        tier = "LOW"
    elif score < RISK_TIER_HIGH_MIN:
        tier = "MODERATE"
    else:
        tier = "HIGH"
    return score, tier


# ---------------------------------------------------------------------------
# 9. satisfaction_composite_and_patient_average
# ---------------------------------------------------------------------------
def satisfaction_composite(taste, temperature, accuracy):
    raw = (TASTE_WEIGHT * Decimal(taste)
           + TEMPERATURE_WEIGHT * Decimal(temperature)
           + ACCURACY_WEIGHT * Decimal(accuracy))
    return rhu(raw, 2)


def patient_satisfaction_average(composites):
    """Average the ALREADY-ROUNDED composites, then round once more."""
    if not composites:
        return None
    total = sum((dec(c) for c in composites), Decimal("0"))
    return rhu(total / Decimal(len(composites)), 2)
