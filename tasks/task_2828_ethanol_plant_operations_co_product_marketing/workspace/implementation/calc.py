"""Every calculation rule from the PRD, implemented literally."""
from decimal import Decimal

from util import D, rhu, dfloor, dceil

# ---------------------------------------------------------------- constants
LBS_PER_BUSHEL = D("56.0")
BASIS_MOISTURE_PCT = D("15.0")
MOISTURE_STEP_HUNDREDTHS = 50
MOISTURE_RATE = D("4.0")
TEST_WEIGHT_STANDARD_TENTHS = 540
TEST_WEIGHT_RATE = D("0.35")
FOREIGN_MATERIAL_FREE_HUNDREDTHS = 300
FOREIGN_MATERIAL_RATE = D("0.15")
DAMAGE_FREE_HUNDREDTHS = 500
DAMAGE_RATE = D("0.08")
AFLATOXIN_LIMIT_PPB = 20
MOISTURE_REJECT_PCT = D("20.00")

LACTIC_THRESHOLD_PPM = 800
LACTIC_RATE = D("0.047")
LACTIC_CAP = D("40")
ACETIC_THRESHOLD_PPM = 300
ACETIC_RATE = D("0.081")
ACETIC_CAP = D("30")
TEMP_BAND_LOW = D("30.0")
TEMP_BAND_HIGH = D("35.0")
TEMP_OUT_OF_BAND_STEP = D("9.75")
TEMP_RATE = D("3.9")
TEMP_CAP = D("20")
HEALTH_WINDOW = 3
HEALTH_WEIGHTS = (D("0.5"), D("0.3"), D("0.2"))
HEALTH_WATCH_THRESHOLD = D("70.00")

BASE_YIELD = D("2.850")
MIN_YIELD = D("2.550")
MAX_YIELD = D("3.050")
STARCH_BONUS_PER_TENTH = D("0.0015")
STARCH_BONUS_CAP = D("0.090")
INTERVENTION_PENALTY_PER = D("0.040")
INTERVENTION_PENALTY_CAP = D("0.100")
INTERVENTION_LIMIT = 2
DDGS_LBS_PER_BUSHEL = D("17.0")
LBS_PER_TON = D("2000")
CORN_OIL_LBS_PER_BUSHEL = D("0.600")

RIN_GALLONS_PER_ETHANOL_GALLON = D("1.02")
RIN_EQUIVALENCE_VALUE = D("1.0")
RIN_D_CODE = 6

DENATURANT_MIN_PCT = D("0.019800")
DENATURANT_MAX_PCT = D("0.029800")

CI_WATERFALL_CAP = D("12.0")
TIER_FACTOR = {"FULL": D("1.00"), "PROVISIONAL": D("0.70")}
STACK_FACTOR_WITH_PREDECESSOR = D("0.50")
STACK_FACTOR_STANDALONE = D("1.00")
LCFS_BENCHMARK_CI = D("79.75")
LCFS_CREDIT_FACTOR = D("81.51")
REVISION_LIMIT = 2

NATGAS_MMBTU_PER_BUSHEL = D("0.0800")
CONVERSION_COST_CENTS_PER_BUSHEL = D("32.50")
DDGS_SBM_RATIO = D("0.92")
CORN_OIL_SBO_RATIO = D("0.80")

COLLAR_PCT = D("0.075")
REBATE_HIGH_THRESHOLD = D("50000.00")
REBATE_HIGH_RATE = D("0.0150")
REBATE_LOW_THRESHOLD = D("20000.00")
REBATE_LOW_RATE = D("0.0075")
FREIGHT_CAP_USD = D("2500.00")
UNIT_DIVISOR = {"DDGS_DRY": D("1"), "DDGS_WET": D("1"), "CORN_OIL": D("100")}

HEDGE_UNIT_SIZE = {"CORN": 5000, "ETHANOL": 29000, "NATGAS": 10000}

COMPLIANCE_MULTIPLIER = {
    "OPEN": D("1.00"),
    "RESTRICTED": D("0.90"),
    "CURTAILED": D("0.60"),
    "SUSPENDED": D("0.00"),
}
PROCUREMENT_MULTIPLIER = {"ADEQUATE": D("1.00"), "SHORT": D("0.75")}
SEVERITY_RANK = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}
POSTURE_BY_RANK = {0: "OPEN", 1: "RESTRICTED", 2: "CURTAILED", 3: "SUSPENDED"}


# ------------------------------------------------- corn delivery settlement
def corn_delivery_weights(gross_weight_lbs, tare_weight_lbs, moisture_pct):
    gross_wet = rhu(
        (D(gross_weight_lbs) - D(tare_weight_lbs)) / LBS_PER_BUSHEL, 2)
    shrink = (D(100) - D(moisture_pct)) / (D(100) - BASIS_MOISTURE_PCT)
    net_dry = rhu(gross_wet * shrink, 2)
    return gross_wet, net_dry


def corn_delivery_discounts(moisture_pct, test_weight, foreign_material_pct,
                            damaged_kernels_pct):
    moisture_h = int(rhu(D(moisture_pct) * 100, 0))
    tw_tenths = int(rhu(D(test_weight) * 10, 0))
    fm_h = int(rhu(D(foreign_material_pct) * 100, 0))
    dk_h = int(rhu(D(damaged_kernels_pct) * 100, 0))

    moisture_steps = dceil(
        D(max(0, moisture_h - 1500)) / D(MOISTURE_STEP_HUNDREDTHS))
    tw_steps = max(0, TEST_WEIGHT_STANDARD_TENTHS - tw_tenths)
    fm_steps = max(0, fm_h - FOREIGN_MATERIAL_FREE_HUNDREDTHS)
    dk_steps = max(0, dk_h - DAMAGE_FREE_HUNDREDTHS)

    moisture_discount = rhu(D(moisture_steps) * MOISTURE_RATE, 2)
    tw_discount = rhu(D(tw_steps) * TEST_WEIGHT_RATE, 2)
    fm_discount = rhu(D(fm_steps) * FOREIGN_MATERIAL_RATE, 2)
    dk_discount = rhu(D(dk_steps) * DAMAGE_RATE, 2)
    total = rhu(moisture_discount + tw_discount + fm_discount + dk_discount, 2)
    return {
        "moisture_discount_cents": moisture_discount,
        "test_weight_discount_cents": tw_discount,
        "foreign_material_discount_cents": fm_discount,
        "damage_discount_cents": dk_discount,
        "discount_cents_per_bushel": total,
    }


def corn_delivery_settlement(delivery, futures_price, basis):
    gross_wet, net_dry = corn_delivery_weights(
        delivery["gross_weight_lbs"], delivery["tare_weight_lbs"],
        delivery["moisture_pct"])
    parts = corn_delivery_discounts(
        delivery["moisture_pct"], delivery["test_weight_lb_per_bu"],
        delivery["foreign_material_pct"], delivery["damaged_kernels_pct"])
    gross_price = rhu(D(futures_price) + D(basis), 2)
    net_price = rhu(max(D("0.00"), gross_price - parts["discount_cents_per_bushel"]), 2)
    result = dict(parts)
    result["gross_wet_bushels"] = gross_wet
    result["net_dry_bushels"] = net_dry
    result["net_price_cents_per_bushel"] = net_price
    result["settlement_amount_cents"] = int(rhu(net_dry * net_price, 0))
    return result


def grading_rejection(aflatoxin_ppb, moisture_pct):
    if int(aflatoxin_ppb) > AFLATOXIN_LIMIT_PPB:
        return "AFLATOXIN_OVER_LIMIT"
    if D(moisture_pct) > MOISTURE_REJECT_PCT:
        return "MOISTURE_OVER_LIMIT"
    return None


# ------------------------------------------------- fermentation health index
def reading_score(lactic_acid_ppm, acetic_acid_ppm, temperature_c):
    lactic_excess = max(0, int(lactic_acid_ppm) - LACTIC_THRESHOLD_PPM)
    lactic_penalty = min(LACTIC_CAP, rhu(D(lactic_excess) * LACTIC_RATE, 2))

    acetic_excess = max(0, int(acetic_acid_ppm) - ACETIC_THRESHOLD_PPM)
    acetic_penalty = min(ACETIC_CAP, rhu(D(acetic_excess) * ACETIC_RATE, 2))

    temp = D(temperature_c)
    if temp < TEMP_BAND_LOW:
        deviation = TEMP_BAND_LOW - temp
    elif temp > TEMP_BAND_HIGH:
        deviation = temp - TEMP_BAND_HIGH
    else:
        deviation = D("0")
    if deviation == 0:
        temp_penalty = D("0.00")
    else:
        temp_penalty = min(
            TEMP_CAP, rhu(TEMP_OUT_OF_BAND_STEP + deviation * TEMP_RATE, 2))

    score = D(100) - lactic_penalty - acetic_penalty - temp_penalty
    if score < 0:
        score = D(0)
    if score > 100:
        score = D(100)
    return rhu(score, 2)


def health_index(scores):
    """`scores` are the reading_score values of the window, most recent first."""
    if not scores:
        return D("100.00")
    weights = list(HEALTH_WEIGHTS[:len(scores)])
    total_weight = sum(weights)
    index = D(0)
    for weight, score in zip(weights, scores):
        normalised = rhu(weight / total_weight, 6)
        index += normalised * D(score)
    return rhu(index, 2)


# ------------------------------------------------------------- batch yield
def starch_bonus(charge_test_weight):
    tenths = int(rhu(D(charge_test_weight) * 10, 0))
    excess = max(0, tenths - TEST_WEIGHT_STANDARD_TENTHS)
    return min(STARCH_BONUS_CAP, rhu(D(excess) * STARCH_BONUS_PER_TENTH, 3))


def health_penalty(index):
    value = D(index)
    if value >= D("90.00"):
        return D("0.000")
    if value >= D("75.00"):
        return D("0.050")
    if value >= D("60.00"):
        return D("0.150")
    return D("0.300")


def intervention_penalty(count):
    return min(INTERVENTION_PENALTY_CAP,
               rhu(D(int(count)) * INTERVENTION_PENALTY_PER, 3))


def batch_yield(corn_bushels, charge_test_weight, index, interventions):
    bonus = starch_bonus(charge_test_weight)
    hpen = health_penalty(index)
    ipen = intervention_penalty(interventions)
    effective = rhu(BASE_YIELD + bonus - hpen - ipen, 3)
    if effective < MIN_YIELD:
        effective = MIN_YIELD
    if effective > MAX_YIELD:
        effective = MAX_YIELD
    bushels = D(corn_bushels)
    return {
        "starch_bonus_gal_per_bushel": bonus,
        "health_penalty_gal_per_bushel": hpen,
        "intervention_penalty_gal_per_bushel": ipen,
        "effective_yield_gal_per_bushel": effective,
        "ethanol_gallons_produced": rhu(bushels * effective, 2),
        "ddgs_tons_produced": rhu(bushels * DDGS_LBS_PER_BUSHEL / LBS_PER_TON, 3),
        "corn_oil_lbs_produced": rhu(bushels * CORN_OIL_LBS_PER_BUSHEL, 2),
    }


# ------------------------------------------------------------------- RINs
def rin_generation(ethanol_gallons):
    eligible = rhu(D(ethanol_gallons) * RIN_GALLONS_PER_ETHANOL_GALLON
                   * RIN_EQUIVALENCE_VALUE, 2)
    return eligible, dfloor(eligible)


# ------------------------------------------------------------- denaturant
def denaturant_spec(neat_gallons, denaturant_gallons):
    output = rhu(D(neat_gallons) + D(denaturant_gallons), 2)
    pct = rhu(D(denaturant_gallons) / output, 6)
    in_spec = DENATURANT_MIN_PCT <= pct <= DENATURANT_MAX_PCT
    return output, pct, in_spec


# ------------------------------------------------------------ CI waterfall
def ci_waterfall(projects):
    """`projects` are CERTIFIED carbon projects in credit order."""
    remaining = CI_WATERFALL_CAP
    credited_by_id = {}
    total = D(0)
    for project in projects:
        tier = TIER_FACTOR[project["certification_tier"]]
        stack = (STACK_FACTOR_WITH_PREDECESSOR
                 if project.get("predecessor_project_id")
                 else STACK_FACTOR_STANDALONE)
        raw = rhu(D(project["verified_reduction_g_per_mj"]) * tier * stack, 3)
        credited = raw if raw < remaining else remaining
        credited = rhu(credited, 3)
        remaining = rhu(remaining - credited, 3)
        credited_by_id[project["id"]] = credited
        total += credited
    return credited_by_id, rhu(total, 3)


def ci_score(baseline, total_credited):
    value = rhu(D(baseline) - D(total_credited), 3)
    if value < 0:
        value = D("0.000")
    return rhu(value, 3)


def lcfs_credit(score):
    gap = LCFS_BENCHMARK_CI - D(score)
    if gap < 0:
        gap = D(0)
    return rhu(gap * LCFS_CREDIT_FACTOR, 3)


# ------------------------------------------------------------ crush margin
def crush_margin(plant, rolling_yield, realized_inputs):
    natgas = rhu(D(plant["mark_natgas_cents_per_mmbtu"]) * NATGAS_MMBTU_PER_BUSHEL, 2)
    conversion = CONVERSION_COST_CENTS_PER_BUSHEL

    mtm_ethanol = rhu(D(plant["mark_ethanol_cents_per_gallon"]) * D(rolling_yield), 2)
    mtm_ddgs = rhu(D(plant["mark_soybean_meal_usd_per_ton"]) * DDGS_SBM_RATIO
                   * DDGS_LBS_PER_BUSHEL / LBS_PER_TON * D(100), 2)
    mtm_oil = rhu(D(plant["mark_sbo_cents_per_lb"]) * CORN_OIL_SBO_RATIO
                  * CORN_OIL_LBS_PER_BUSHEL, 2)
    mtm_corn = rhu(D(plant["mark_corn_cents_per_bushel"]), 2)
    mtm_gross = rhu(mtm_ethanol + mtm_ddgs + mtm_oil, 2)
    mtm_net = rhu(mtm_gross - mtm_corn - natgas - conversion, 2)

    bushels = D(realized_inputs["bushels_completed"])
    if bushels <= 0:
        real_ethanol = D("0.00")
        real_coproduct = D("0.00")
        real_corn = D("0.00")
        real_net = D("0.00")
    else:
        real_ethanol = rhu(D(realized_inputs["ethanol_revenue_cents"]) / bushels, 2)
        real_coproduct = rhu(D(realized_inputs["coproduct_revenue_cents"]) / bushels, 2)
        net_dry_total = D(realized_inputs["settled_net_dry_bushels"])
        if net_dry_total <= 0:
            real_corn = D("0.00")
        else:
            real_corn = rhu(D(realized_inputs["settled_cost_cents"]) / net_dry_total, 2)
        real_net = rhu(real_ethanol + real_coproduct - real_corn - natgas - conversion, 2)

    return {
        "rolling_yield": rhu(rolling_yield, 3),
        "natgas_cost_cents_per_bushel": natgas,
        "conversion_cost_cents_per_bushel": rhu(conversion, 2),
        "mark_to_market": {
            "ethanol_cents_per_bushel": mtm_ethanol,
            "ddgs_cents_per_bushel": mtm_ddgs,
            "corn_oil_cents_per_bushel": mtm_oil,
            "corn_cost_cents_per_bushel": mtm_corn,
            "gross_cents_per_bushel": mtm_gross,
            "net_cents_per_bushel": mtm_net,
        },
        "realized": {
            "ethanol_cents_per_bushel": real_ethanol,
            "coproduct_cents_per_bushel": real_coproduct,
            "corn_cost_cents_per_bushel": real_corn,
            "net_cents_per_bushel": real_net,
        },
        "variant_delta_cents_per_bushel": rhu(real_net - mtm_net, 2),
    }


# ------------------------------------------------------- co-product pricing
def reference_mark(plant, product):
    if plant is None:
        return None
    if product in ("DDGS_DRY", "DDGS_WET"):
        return plant.get("mark_soybean_meal_usd_per_ton")
    return plant.get("mark_sbo_cents_per_lb")


def index_quote_price(mark, index_pct):
    return rhu(D(mark) * D(index_pct), 2)


def settlement_price(sale, current_mark):
    if sale["pricing_basis"] == "FLAT":
        return D(sale["quoted_price"]), None, None
    quoted = D(sale["quoted_price"])
    restruck = rhu(D(current_mark) * D(sale["index_pct"]), 2)
    floor = rhu(quoted * (D(1) - COLLAR_PCT), 2)
    ceiling = rhu(quoted * (D(1) + COLLAR_PCT), 2)
    settled = restruck
    if settled < floor:
        settled = floor
    if settled > ceiling:
        settled = ceiling
    return rhu(settled, 2), floor, ceiling


def coproduct_invoice(product, quantity, settlement, freight_rate):
    divisor = UNIT_DIVISOR[product]
    subtotal = rhu(D(quantity) * D(settlement) / divisor, 2)
    if subtotal >= REBATE_HIGH_THRESHOLD:
        rate = REBATE_HIGH_RATE
    elif subtotal >= REBATE_LOW_THRESHOLD:
        rate = REBATE_LOW_RATE
    else:
        rate = D("0.0000")
    rebate = rhu(subtotal * rate, 2)
    freight = rhu(D(quantity) * D(freight_rate), 2)
    if freight > FREIGHT_CAP_USD:
        freight = FREIGHT_CAP_USD
    net = rhu(subtotal - rebate - freight, 2)
    return {
        "subtotal_usd": subtotal,
        "volume_rebate_usd": rebate,
        "freight_usd": freight,
        "net_usd": net,
        "invoice_amount_cents": int(rhu(net * D(100), 0)),
    }


# --------------------------------------------------------------- hedge P&L
def hedge_sign(direction):
    return D(1) if direction == "LONG" else D(-1)


def hedge_slice_pnl(direction, commodity, entry_price, exit_price, contracts):
    unit = D(HEDGE_UNIT_SIZE[commodity])
    return int(rhu(hedge_sign(direction) * (D(exit_price) - D(entry_price))
                   * unit * D(int(contracts)), 0))


def hedge_unrealized(direction, commodity, entry_price, mark, contracts_open):
    if int(contracts_open) == 0 or mark is None:
        return 0
    unit = D(HEDGE_UNIT_SIZE[commodity])
    return int(rhu(hedge_sign(direction) * (D(mark) - D(entry_price))
                   * unit * D(int(contracts_open)), 0))


# ------------------------------------------------------------ permit window
def rolling_average(values):
    if not values:
        return None, 0
    total = sum((D(v) for v in values), D(0))
    return rhu(total / D(len(values)), 3), len(values)


# ------------------------------------------------------------- grind cap
def grind_cap(base, compliance_posture, procurement_posture):
    return dfloor(D(base) * COMPLIANCE_MULTIPLIER[compliance_posture]
                  * PROCUREMENT_MULTIPLIER[procurement_posture])


# ------------------------------------------------------------ intervals
def windows_overlap_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def closed_intervals_conflict(a_start, a_end, b_start, b_end):
    return b_start <= a_end and a_start <= b_end
