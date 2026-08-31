"""Calculation rules and their constants."""
from decimal import Decimal

import store
from core import D, floor_int, log10, plus_days, pow10, rhu, rhu_int

# ---- constants -----------------------------------------------------------
VISCOSITY_OFFSET = D("0.7")
BLEND_DENSITY_KG_PER_L = D("0.860")
MAX_HEEL_RATIO_CROSS_FAMILY = D("0.005000")
MAX_HEEL_RATIO_SAME_FAMILY = D("0.020000")
CLAIM_HEEL_LIMIT_CROSS_FAMILY = D("0.001000")
CLAIM_HEEL_LIMIT_SAME_FAMILY = D("0.010000")
HEEL_RETENTION_PCT = D("0.5")
MIN_RETAIN_COUNT = 2
REQUIRED_TESTS = ["KV100", "TBN"]
RETENTION_DAYS_STANDARD = 365
RETENTION_DAYS_CLAIM_BEARING = 1095
CLAIM_VALIDITY_DAYS = 730
CHANGEOVER_BUFFER_MINUTES = 120

PACKAGE_RATE_CENTS_PER_L = {
    "BULK": D("320"),
    "IBC_1000L": D("380"),
    "DRUM_205L": D("425"),
    "PAIL_20L": D("505"),
    "CASE_12X1L": D("640"),
}
TIER_DISCOUNT_PCT = {"TIER_A": D("12.0"), "TIER_B": D("7.5"), "TIER_C": D("0.0")}
PRIVATE_LABEL_UPLIFT_PCT = D("4.5")

BULK_FREE_FREIGHT_L = D("4000")
BULK_MIN_FREIGHT_CENTS = D("48000")
PACKAGED_FREIGHT_FREE_THRESHOLD_CENTS = 1000000
PACKAGED_FREIGHT_MID_THRESHOLD_CENTS = 500000
PACKAGED_FREIGHT_MID_CENTS = 22500
PACKAGED_FREIGHT_LOW_CENTS = 39500
TAKEBACK_CREDIT_CAP_PCT = D("15")

TAKEBACK_FLAT_RATE_CENTS_PER_L = D("18")
TAKEBACK_BASE_RATE_CENTS_PER_L = D("25")
MAX_CONTAMINATION_PCT = D("25")


# ---- recipe_predicted_kv100 ---------------------------------------------
def recipe_components(recipe_id):
    rows = store.where("RecipeComponent", blend_recipe_id=recipe_id)
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def recipe_predicted_kv100(components):
    z_blend = Decimal(0)
    for comp in components:
        z_c = log10(log10(D(comp["nominal_kv100_cst"]) + VISCOSITY_OFFSET))
        z_blend += (D(comp["mass_fraction_pct"]) / D(100)) * z_c
    predicted = pow10(pow10(z_blend)) - VISCOSITY_OFFSET
    return rhu(predicted, 3)


def recipe_additive_treat_pct(components):
    total = Decimal(0)
    for comp in components:
        if comp["component_type"] == "ADDITIVE_PACKAGE":
            total += D(comp["mass_fraction_pct"])
    return rhu(total, 2)


def fraction_sum(components):
    total = Decimal(0)
    for comp in components:
        total += D(comp["mass_fraction_pct"])
    return total


# ---- qc_viscosity_conformance -------------------------------------------
def viscosity_band(target, tolerance_pct):
    lower = rhu(D(target) * (Decimal(1) - D(tolerance_pct) / D(100)), 3)
    upper = rhu(D(target) * (Decimal(1) + D(tolerance_pct) / D(100)), 3)
    return lower, upper


def in_band(value, lower, upper):
    return lower <= D(value) <= upper


# ---- batch_component_requirement ----------------------------------------
def charge_mass_kg(charge_volume_l):
    return rhu(D(charge_volume_l) * BLEND_DENSITY_KG_PER_L, 3)


def component_requirements(components, mass_kg):
    """Ordered mapping component_code -> required_kg."""
    required = {}
    for comp in components:
        required[comp["component_code"]] = rhu(
            D(mass_kg) * D(comp["mass_fraction_pct"]) / D(100), 3)
    return required


# ---- component_lot_availability -----------------------------------------
def lot_available_kg(lot):
    drawn = Decimal(0)
    for draw in store.where("ComponentDraw", component_lot_id=lot["id"]):
        if draw["status"] in ("RESERVED", "CONSUMED"):
            drawn += D(draw["drawn_kg"])
    return rhu(D(lot["received_kg"]) - drawn, 3)


def refresh_lot(lot):
    lot["available_kg"] = lot_available_kg(lot)
    return lot["available_kg"]


def candidate_lots(component_code):
    """AVAILABLE lots of the code in draw order.  Lot id is never a sort key."""
    rows = [r for r in store.all_rows("ComponentLot")
            if r["component_code"] == component_code and r["status"] == "AVAILABLE"]
    return sorted(rows, key=lambda r: (r["created_at"], -D(r["received_kg"]),
                                       r["unit_cost_cents_per_kg"], r["_seq"]))


def quarantined_lots(component_code):
    return [r for r in store.all_rows("ComponentLot")
            if r["component_code"] == component_code and r["status"] == "QUARANTINED"]


# ---- heel_contamination_ratio -------------------------------------------
def heel_families(tank, spec):
    heel = tank["heel_additive_family"]
    family = spec["additive_family"]
    cross = heel != "NONE" and heel != family
    same = heel == family
    return cross, same


def heel_ratio(tank, charge_volume_l):
    heel = D(tank["heel_volume_l"])
    denominator = heel + D(charge_volume_l)
    if denominator == 0:
        return rhu(0, 6)
    return rhu(heel / denominator, 6)


def heel_limit(cross, same):
    if cross:
        return MAX_HEEL_RATIO_CROSS_FAMILY
    if same:
        return MAX_HEEL_RATIO_SAME_FAMILY
    return Decimal(1)


def claim_heel_limit(cross, same):
    if cross:
        return CLAIM_HEEL_LIMIT_CROSS_FAMILY
    if same:
        return CLAIM_HEEL_LIMIT_SAME_FAMILY
    return Decimal(1)


# ---- batch_component_cost ------------------------------------------------
def moving_average_cost(required):
    total = Decimal(0)
    for code, required_kg in required.items():
        lots = candidate_lots(code)
        numerator = Decimal(0)
        denominator = Decimal(0)
        for lot in lots:
            available = D(lot["available_kg"])
            numerator += available * D(lot["unit_cost_cents_per_kg"])
            denominator += available
        wavg = (numerator / denominator) if denominator != 0 else Decimal(0)
        total += D(required_kg) * wavg
    return rhu_int(total)


def consumption_layer_cost(batch_id):
    total = Decimal(0)
    for draw in store.where("ComponentDraw", blend_batch_id=batch_id):
        if draw["status"] == "CONSUMED":
            total += D(draw["drawn_kg"]) * D(draw["unit_cost_cents_per_kg"])
    return rhu_int(total)


# ---- retain / claim windows ---------------------------------------------
def retention_until(spec_id, retained_at):
    claim_bearing = any(
        c["status"] == "ACTIVE"
        for c in store.where("ApprovalClaim", product_spec_id=spec_id))
    days = RETENTION_DAYS_CLAIM_BEARING if claim_bearing else RETENTION_DAYS_STANDARD
    return plus_days(retained_at, days)


def claim_valid_until(approved_at):
    return plus_days(approved_at, CLAIM_VALIDITY_DAYS)


# ---- order_line_pricing --------------------------------------------------
def line_rate(config, customer):
    base = PACKAGE_RATE_CENTS_PER_L[config["package_type"]]
    discount = TIER_DISCOUNT_PCT[customer["contract_tier"]]
    uplift = PRIVATE_LABEL_UPLIFT_PCT if config["private_label"] else Decimal(0)
    return base * (Decimal(1) - discount / D(100)) * (Decimal(1) + uplift / D(100))


def price_line(line, config, customer):
    rate = line_rate(config, customer)
    line["volume_l"] = rhu(D(line["quantity_units"]) * D(config["fill_volume_l"]), 2)
    line["line_total_cents"] = rhu_int(D(line["volume_l"]) * rate)
    line["unit_price_cents"] = rhu_int(D(config["fill_volume_l"]) * rate)
    return line


# ---- order_freight_and_credit -------------------------------------------
def freight_cents(order, subtotal_cents, total_volume_l):
    if order["delivery_mode"] == "BULK_DELIVERY":
        if D(total_volume_l) >= BULK_FREE_FREIGHT_L:
            return 0
        return rhu_int(BULK_MIN_FREIGHT_CENTS *
                       (Decimal(1) - D(total_volume_l) / BULK_FREE_FREIGHT_L))
    if subtotal_cents >= PACKAGED_FREIGHT_FREE_THRESHOLD_CENTS:
        return 0
    if subtotal_cents >= PACKAGED_FREIGHT_MID_THRESHOLD_CENTS:
        return PACKAGED_FREIGHT_MID_CENTS
    return PACKAGED_FREIGHT_LOW_CENTS


def credit_cap(pre_credit_total_cents):
    return floor_int(D(pre_credit_total_cents) * TAKEBACK_CREDIT_CAP_PCT / D(100))


# ---- takeback_credit -----------------------------------------------------
def takeback_variant(collection, customer):
    if collection["status"] == "COLLECTED":
        return "FLAT_RATE"
    if customer["contract_tier"] == "TIER_A":
        return "FLAT_RATE"
    return "ASSAY_ADJUSTED"


def takeback_credit_cents(collection, variant):
    volume = D(collection["collected_volume_l"])
    if variant == "FLAT_RATE":
        return rhu_int(volume * TAKEBACK_FLAT_RATE_CENTS_PER_L)
    net_factor = (Decimal(1)
                  - D(collection["water_pct"]) / D(100)
                  - D(collection["sediment_pct"]) / D(100))
    credit = rhu_int(volume * TAKEBACK_BASE_RATE_CENTS_PER_L * net_factor)
    return max(credit, 0)


# ---- customer_takeback_credit_balance -----------------------------------
def customer_balance(customer_id):
    granted = 0
    for collection in store.where("TakebackCollection", customer_id=customer_id):
        if collection["status"] == "CREDITED":
            granted += collection["credit_cents"]
    applied = 0
    for order in store.where("Order", customer_id=customer_id):
        if order["status"] in ("CONFIRMED", "HOLD", "INVOICED"):
            applied += order["takeback_credit_applied_cents"]
    return granted - applied


def rhu_int_public(value):
    return rhu_int(value)
