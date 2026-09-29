"""Every calculation rule of the PRD, in exact arithmetic."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

CENT = Decimal("1")
TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal("100")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu2(value):
    """Round half up to two decimals."""
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def rhu0(value):
    """Round half up to a whole cent."""
    return int(D(value).quantize(CENT, rounding=ROUND_HALF_UP))


def floor0(value):
    """Floor to a whole cent."""
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


# --------------------------------------------------------------------------
# 3.1  category gap score
# --------------------------------------------------------------------------
TIERS = ("OPENING_PRICE", "NBE", "PREMIUM")


def category_gap_score(sales_cents, pl_share_pct, velocity, nb_price_cents):
    sales_component = min(Decimal("40.00"), rhu2(D(sales_cents) / Decimal(25000000)))
    share_component = max(Decimal("0.00"), rhu2(Decimal("35.00") - D(pl_share_pct)))
    velocity_component = min(Decimal("15.00"), rhu2(D(velocity) / Decimal(40)))
    if D(nb_price_cents) >= Decimal(400):
        price_component = Decimal("10.00")
    else:
        price_component = rhu2(D(nb_price_cents) / Decimal(40))
    total = sales_component + share_component + velocity_component + price_component
    score = rhu2(min(Decimal("100.00"), total))
    if score >= Decimal("70.00") and D(nb_price_cents) >= Decimal(500):
        tier = "PREMIUM"
    elif score >= Decimal("45.00"):
        tier = "NBE"
    else:
        tier = "OPENING_PRICE"
    return score, tier


# --------------------------------------------------------------------------
# 3.3  landed unit cost (two variants over one formula)
# --------------------------------------------------------------------------
def landed_unit_cost(base_cents, yield_pct, scrap_cents, freight_cents_per_pallet, units_per_pallet):
    yield_fraction = D(yield_pct) / HUNDRED
    yield_adjusted = D(base_cents) / yield_fraction
    freight_per_unit = D(freight_cents_per_pallet) / D(units_per_pallet)
    return rhu0(yield_adjusted + freight_per_unit + D(scrap_cents))


SCRAP_BY_RESULT = {"PASS": 0, "CONDITIONAL": 3}


# --------------------------------------------------------------------------
# 3.2  plant audit result
# --------------------------------------------------------------------------
def audit_result(food_safety, sanitation, capacity, traceability):
    lowest = min(food_safety, sanitation, capacity, traceability)
    if food_safety >= 90 and lowest >= 80:
        return "PASS"
    if food_safety >= 80 and lowest >= 70:
        return "CONDITIONAL"
    return "FAIL"


# --------------------------------------------------------------------------
# 3.4  bench-top parity index and consumer panel preference share
# --------------------------------------------------------------------------
def bench_top_parity_index(appearance, aroma, texture, flavor):
    penalty = (
        Decimal(8) * abs(D(flavor))
        + Decimal(6) * abs(D(texture))
        + Decimal(4) * abs(D(aroma))
        + Decimal(2) * abs(D(appearance))
    )
    index = rhu2(max(Decimal("0.00"), Decimal(100) - penalty))
    if index >= Decimal("95.00") and D(flavor) > 0:
        verdict = "SUPERIOR"
    elif index >= Decimal("85.00"):
        verdict = "PARITY"
    else:
        verdict = "INFERIOR"
    return index, verdict


def panel_preference_share(prefer_pl, prefer_nb):
    denominator = D(prefer_pl) + D(prefer_nb)
    if denominator == 0:
        share = Decimal("0.00")
    else:
        share = rhu2(D(prefer_pl) * HUNDRED / denominator)
    if share >= Decimal("55.00"):
        verdict = "SUPERIOR"
    elif share >= Decimal("45.00"):
        verdict = "PARITY"
    else:
        verdict = "INFERIOR"
    return share, verdict


# --------------------------------------------------------------------------
# 3.5  nutrition panel declaration
# --------------------------------------------------------------------------
def _nearest_multiple(value, multiple):
    step = Decimal(multiple)
    return int((D(value) / step).quantize(CENT, rounding=ROUND_HALF_UP) * step)


def declare_calories(exact):
    exact = D(exact)
    if exact < Decimal(5):
        return 0
    if exact <= Decimal(50):
        return _nearest_multiple(exact, 5)
    return _nearest_multiple(exact, 10)


def declare_macro(grams):
    grams = D(grams)
    if grams < Decimal("0.5"):
        return Decimal("0.0")
    if grams < Decimal(5):
        return (grams * 2).quantize(CENT, rounding=ROUND_HALF_UP) / Decimal(2)
    return grams.quantize(CENT, rounding=ROUND_HALF_UP)


def declare_sodium(milligrams):
    milligrams = D(milligrams)
    if milligrams < Decimal(5):
        return 0
    if milligrams <= Decimal(140):
        return _nearest_multiple(milligrams, 5)
    return _nearest_multiple(milligrams, 10)


NUTRIENT_INPUTS = (
    "fat_g_per_100g",
    "satfat_g_per_100g",
    "carb_g_per_100g",
    "fiber_g_per_100g",
    "sugars_g_per_100g",
    "added_sugars_g_per_100g",
    "protein_g_per_100g",
    "sodium_mg_per_100g",
)


def nutrition_panel(round_row):
    """Returns the nine declared figures.  Per-serving amounts are unrounded."""
    serving = D(round_row["serving_size_g"])
    per_serving = {}
    for name in NUTRIENT_INPUTS:
        per_serving[name] = D(round_row[name]) * serving / HUNDRED
    fat = per_serving["fat_g_per_100g"]
    carb = per_serving["carb_g_per_100g"]
    fiber = per_serving["fiber_g_per_100g"]
    protein = per_serving["protein_g_per_100g"]
    calories_exact = (
        Decimal(4) * (carb - fiber) + Decimal(2) * fiber + Decimal(4) * protein + Decimal(9) * fat
    )
    return {
        "declared_calories": declare_calories(calories_exact),
        "declared_fat_g": declare_macro(fat),
        "declared_satfat_g": declare_macro(per_serving["satfat_g_per_100g"]),
        "declared_carb_g": declare_macro(carb),
        "declared_fiber_g": declare_macro(fiber),
        "declared_sugars_g": declare_macro(per_serving["sugars_g_per_100g"]),
        "declared_added_sugars_g": declare_macro(per_serving["added_sugars_g_per_100g"]),
        "declared_protein_g": declare_macro(protein),
        "declared_sodium_mg": declare_sodium(per_serving["sodium_mg_per_100g"]),
    }


# --------------------------------------------------------------------------
# 3.8  complaint trend and supplier composite score
# --------------------------------------------------------------------------
SEVERITY_WEIGHTS = {"CRITICAL": 5, "MAJOR": 2, "MINOR": 1}


def complaint_ppm(weighted_points, trailing_units):
    if trailing_units == 0:
        return Decimal("0.00")
    return rhu2(D(weighted_points) * Decimal(1000000) / D(trailing_units))


def posture_for_ppm(ppm):
    if D(ppm) >= Decimal("150.00"):
        return "PROBATION"
    if D(ppm) >= Decimal("60.00"):
        return "WATCH"
    return "GREEN"


def audit_component(audit):
    if audit is None:
        return Decimal("80.00")
    return rhu2(
        Decimal("0.40") * D(audit["food_safety_score"])
        + Decimal("0.25") * D(audit["sanitation_score"])
        + Decimal("0.20") * D(audit["traceability_score"])
        + Decimal("0.15") * D(audit["capacity_score"])
    )


def complaint_component(weighted_points):
    return max(Decimal("0.00"), rhu2(Decimal(100) - Decimal("2.5") * D(weighted_points)))


def delivery_component(on_time_count, total_count):
    if total_count == 0:
        return Decimal("100.00")
    return rhu2(D(on_time_count) * HUNDRED / D(total_count))


def composite_score(audit_part, complaint_part, delivery_part):
    return rhu2(
        Decimal("0.50") * D(audit_part)
        + Decimal("0.30") * D(complaint_part)
        + Decimal("0.20") * D(delivery_part)
    )


# --------------------------------------------------------------------------
# 3.9  cost change settlement, ten ordered steps
# --------------------------------------------------------------------------
TIER_CAP_PCT = {"T1": Decimal("3.00"), "T2": Decimal("6.50"), "T3": Decimal("9.00")}
MAX_NEGOTIATION_ROUNDS = 3
OFFSET_FEE_PCT = Decimal("12.50")


def cost_change_settlement(old_base_cents, ingredient, packaging, conversion):
    requested_total = int(ingredient) + int(packaging) + int(conversion)
    old_base = int(old_base_cents)
    raw_increase = requested_total - old_base
    if old_base == 0:
        increase_pct = Decimal("0.00") if raw_increase <= 0 else Decimal("100.00") * D(raw_increase)
    else:
        increase_pct = rhu2(D(raw_increase) * HUNDRED / D(old_base))
    if increase_pct <= Decimal("3.00"):
        tier = "T1"
    elif increase_pct <= Decimal("8.00"):
        tier = "T2"
    else:
        tier = "T3"
    tier_cap = floor0(D(old_base) * TIER_CAP_PCT[tier] / HUNDRED)
    capped_increase = min(raw_increase, tier_cap)
    offset_fee = rhu0(D(capped_increase) * OFFSET_FEE_PCT / HUNDRED)
    net_increase = capped_increase - offset_fee
    return {
        "raw_increase_cents": raw_increase,
        "increase_pct": increase_pct,
        "escalation_tier": tier,
        "capped_increase_cents": capped_increase,
        "offset_fee_cents": offset_fee,
        "net_increase_cents": net_increase,
    }


# --------------------------------------------------------------------------
# 3.6  specification lock pricing
# --------------------------------------------------------------------------
TIER_SLOTTING_BASE = {"OPENING_PRICE": 150000, "NBE": 250000, "PREMIUM": 400000}
TIER_MARGIN_PCT = {
    "OPENING_PRICE": Decimal("22.00"),
    "NBE": Decimal("30.00"),
    "PREMIUM": Decimal("38.00"),
}


def ceil_to_nine(amount):
    amount = int(amount)
    candidate = amount - (amount % 10) + 9
    if candidate < amount:
        candidate += 10
    return candidate


def spec_lock_pricing(landed_effective_cents, tier, moq_units):
    variable = rhu0(D(landed_effective_cents) * D(moq_units) * Decimal("0.50") / HUNDRED)
    slotting_fee = TIER_SLOTTING_BASE[tier] + variable
    margin_fraction = Decimal(1) - (TIER_MARGIN_PCT[tier] / HUNDRED)
    raw_retail = rhu0(D(landed_effective_cents) / margin_fraction)
    return slotting_fee, ceil_to_nine(raw_retail)
