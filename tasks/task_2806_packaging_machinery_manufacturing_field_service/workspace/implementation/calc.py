"""The calculation rules of PRD 3 / scaffold 1.3.

Every rule is evaluated on exact rationals and rounded exactly where the
specification says it is rounded -- never before.
"""
from decimal import Decimal
from fractions import Fraction

from nums import ceil_frac, round_half_up_dec, round_half_up_int, to_frac

HUNDRED = Fraction(100)

# ---- constants -----------------------------------------------------------
MAX_TRIAL_RETESTS = 2
STANDARD_RATIO_FLOOR_PCT = Decimal("90.00")
HEAVY_DUTY_RATIO_FLOOR_PCT = Decimal("75.00")

T1_FLOOR_CENTS = 25000000
T2_FLOOR_CENTS = 75000000
T3_FLOOR_CENTS = 150000000
FEE_PCT = {"NONE": Decimal("6.00"), "T1": Decimal("5.00"),
           "T2": Decimal("4.00"), "T3": Decimal("3.00")}

REFERENCE_RATE_FLOOR_CPM = 1

MIN_FAT_CONTAINERS = 500
MIN_SAT_CONTAINERS = 200
REWORK_DAYS_PER_FAT_FAILURE = 7
MAX_FAT_FAILURES = 3

KIT_ASSEMBLY_QTY_PER_DAY = 4
FAMILY_CHANGE_DAYS = 10
SAME_FAMILY_DAYS = 3
OUT_OF_RANGE_DAYS = 15
MIN_KIT_LEAD_DAYS = 5
MAX_QUOTED_LEAD_DAYS = 180
KIT_MARKUP_PCT = Decimal("17.50")
KIT_ENGINEERING_FEE_CENTS = 120000

DEFECT_CAUSE_FLOOR_PCT = Decimal("80.00")
VARIATION_CAUSE_CEILING_PCT = Decimal("20.00")
VARIATION_TOLERANCE_PCT = Decimal("5.00")
TIER_SHARE_PCT = {"BRONZE": Decimal("50.00"), "SILVER": Decimal("75.00"),
                  "GOLD": Decimal("100.00")}

RESTRICT_THRESHOLD_CENTS = 50000

REVIEW_PERIOD_DAYS = 30
DAYS_PER_YEAR = 365
OBSOLESCENCE_MULTIPLIER = {"ACTIVE": Decimal("1.00"),
                           "NOTICE_ISSUED": Decimal("1.50"),
                           "LAST_TIME_BUY": Decimal("3.00"),
                           "OBSOLETE": Decimal("0.00")}
STOCK_SAFETY_FACTOR = {"A": Decimal("0.50"), "B": Decimal("0.25"),
                       "C": Decimal("0.10")}
STOCK_SERVICE_FACTOR = {"A": Decimal("1.60"), "B": Decimal("1.30"),
                        "C": Decimal("1.05")}
OBSOLESCENCE_CHAIN = ["ACTIVE", "NOTICE_ISSUED", "LAST_TIME_BUY", "OBSOLETE"]


# ---- 1. trial configuration recommendation -------------------------------
def trial_config_recommendation(measured_rate_cpm, nameplate_rate_cpm,
                                product_variation_pct, outcome):
    rate_ratio_pct = round_half_up_dec(
        to_frac(measured_rate_cpm) / to_frac(nameplate_rate_cpm) * HUNDRED, 2)
    effective_ratio_pct = round_half_up_dec(
        to_frac(rate_ratio_pct) - to_frac(product_variation_pct), 2)
    if outcome == "REJECT":
        recommendation = "NOT_FEASIBLE"
    elif effective_ratio_pct >= STANDARD_RATIO_FLOOR_PCT:
        recommendation = "STANDARD"
    elif effective_ratio_pct >= HEAVY_DUTY_RATIO_FLOOR_PCT:
        recommendation = "HEAVY_DUTY"
    else:
        recommendation = "NOT_FEASIBLE"
    return rate_ratio_pct, effective_ratio_pct, recommendation


# ---- 2. order roll-up ----------------------------------------------------
def order_total_rollup(equipment_price_cents, change_parts_price_cents):
    pre_fee_subtotal_cents = equipment_price_cents + change_parts_price_cents
    if pre_fee_subtotal_cents >= T3_FLOOR_CENTS:
        tier = "T3"
    elif pre_fee_subtotal_cents >= T2_FLOOR_CENTS:
        tier = "T2"
    elif pre_fee_subtotal_cents >= T1_FLOOR_CENTS:
        tier = "T1"
    else:
        tier = "NONE"
    fee_pct = FEE_PCT[tier]
    commissioning_fee_cents = round_half_up_int(
        to_frac(pre_fee_subtotal_cents) * to_frac(fee_pct) / HUNDRED)
    order_total_cents = pre_fee_subtotal_cents + commissioning_fee_cents
    return tier, commissioning_fee_cents, order_total_cents


# ---- 3. performance guarantee attainment ---------------------------------
def guarantee_attainment(measured_rate_cpm, measured_efficiency_pct,
                         nameplate_rate_cpm, guarantee_basis,
                         product_variation_pct, guarantee_efficiency_pct):
    if guarantee_basis == "PRODUCT_ADJUSTED":
        reference = (to_frac(nameplate_rate_cpm)
                     * (Fraction(1) - to_frac(product_variation_pct) / HUNDRED))
        if reference < REFERENCE_RATE_FLOOR_CPM:
            reference = to_frac(REFERENCE_RATE_FLOOR_CPM)
    else:
        reference = to_frac(nameplate_rate_cpm)
    attainment_pct = round_half_up_dec(
        to_frac(measured_rate_cpm) / reference * to_frac(measured_efficiency_pct), 2)
    guarantee_met = attainment_pct >= to_frac(guarantee_efficiency_pct)
    return attainment_pct, bool(guarantee_met)


# ---- 4. format kit lead time --------------------------------------------
def format_kit_lead_time(components, kit_family, current_format_family,
                         kit_diameter_mm, min_diameter_mm, max_diameter_mm):
    max_component_lead_days = max(int(c["lead_time_days"]) for c in components)
    total_qty = sum(int(c["qty"]) for c in components)
    assembly_days = ceil_frac(Fraction(total_qty, KIT_ASSEMBLY_QTY_PER_DAY))
    family_change_days = (FAMILY_CHANGE_DAYS
                          if kit_family != current_format_family
                          else SAME_FAMILY_DAYS)
    out_of_range_days = (OUT_OF_RANGE_DAYS
                         if (kit_diameter_mm < min_diameter_mm
                             or kit_diameter_mm > max_diameter_mm) else 0)
    candidate_a = max_component_lead_days + family_change_days
    candidate_b = assembly_days + out_of_range_days + MIN_KIT_LEAD_DAYS
    return min(MAX_QUOTED_LEAD_DAYS, max(candidate_a, candidate_b))


# ---- 5. format kit price ------------------------------------------------
def format_kit_price(components):
    markup = Fraction(1) + to_frac(KIT_MARKUP_PCT) / HUNDRED
    total = 0
    for component in components:
        line = to_frac(int(component["unit_price_cents"])) * int(component["qty"]) * markup
        total += round_half_up_int(line)
    return total + KIT_ENGINEERING_FEE_CENTS


# ---- 6. claim cause classification --------------------------------------
def claim_cause_classification(lines):
    claimed_cost_cents = sum(int(line["amount_cents"]) for line in lines)
    if claimed_cost_cents <= 0:
        return claimed_cost_cents, Decimal("0.00"), "UNDETERMINED"
    weighted = sum(
        (to_frac(int(line["amount_cents"])) * to_frac(line["defect_attribution_pct"])
         for line in lines), Fraction(0))
    weighted_defect_pct = round_half_up_dec(weighted / to_frac(claimed_cost_cents), 2)
    if weighted_defect_pct >= DEFECT_CAUSE_FLOOR_PCT:
        cause = "MACHINE_DEFECT"
    elif weighted_defect_pct <= VARIATION_CAUSE_CEILING_PCT:
        cause = "PRODUCT_VARIATION"
    else:
        cause = "MIXED"
    return claimed_cost_cents, weighted_defect_pct, cause


# ---- 7. claim cost apportionment ----------------------------------------
def line_effective_pct(defect_attribution_pct, product_variation_pct):
    if to_frac(product_variation_pct) <= to_frac(VARIATION_TOLERANCE_PCT):
        return to_frac(defect_attribution_pct)
    excess = to_frac(product_variation_pct) - to_frac(VARIATION_TOLERANCE_PCT)
    return to_frac(round_half_up_dec(
        to_frac(defect_attribution_pct) * (Fraction(1) - excess / HUNDRED), 2))


def claim_cost_apportionment(lines, product_variation_pct):
    """Returns (per-line shares in the given order, oem_share_cents)."""
    shares = []
    for line in lines:
        effective = line_effective_pct(line["defect_attribution_pct"],
                                       product_variation_pct)
        shares.append(round_half_up_int(
            to_frac(int(line["amount_cents"])) * effective / HUNDRED))
    return shares, sum(shares)


# ---- 8. goodwill charge -------------------------------------------------
def claim_goodwill_charge(oem_share_cents, tier, goodwill_budget_cents):
    absorbed = round_half_up_int(
        to_frac(oem_share_cents) * to_frac(TIER_SHARE_PCT[tier]) / HUNDRED)
    return min(absorbed, goodwill_budget_cents)


# ---- 9. coverage posture -----------------------------------------------
def coverage_posture(goodwill_budget_cents):
    if goodwill_budget_cents == 0:
        return "BUDGET_EXHAUSTED"
    if 0 < goodwill_budget_cents <= RESTRICT_THRESHOLD_CENTS:
        return "RESTRICTED"
    return "OPEN"


# ---- 10. spare-parts stocking quantity ---------------------------------
def spare_stocking_qty(annual_usage_qty, unit_lead_time_days, criticality,
                       basis, obsolescence_status):
    multiplier = to_frac(OBSOLESCENCE_MULTIPLIER[obsolescence_status])
    daily_usage = Fraction(int(annual_usage_qty), DAYS_PER_YEAR)
    if basis == "LEAD_TIME_DEMAND":
        factor = Fraction(1) + to_frac(STOCK_SAFETY_FACTOR[criticality])
        raw = daily_usage * int(unit_lead_time_days) * factor * multiplier
    else:
        factor = to_frac(STOCK_SERVICE_FACTOR[criticality])
        raw = (daily_usage * (int(unit_lead_time_days) + REVIEW_PERIOD_DAYS)
               * factor * multiplier)
    return ceil_frac(raw)
