"""Named constants and the thirteen calculations of the PRD.

Every constant here is named in the PRD prose; nothing is invented.
"""

from decimal import Decimal

from core import dec, floor_int, round_cents, round_half_up

# --- PRD 3.4 production allocation ----------------------------------------
ATTACH_RATE = Decimal("0.018")            # packs per forecast shopper
PACKS_PER_LINEAR_FT = Decimal("9")        # packs per linear foot of case
PACKS_PER_CERTIFIED_CHEF = Decimal("200")
RICE_KG_PER_PACK = Decimal("0.12")        # 120 g of cooked rice per pack

POSTURE_FACTORS = {
    "CLEAR": Decimal("1.00"),
    "WATCH": Decimal("0.85"),
    "RESTRICTED": Decimal("0.50"),
    "LOCKDOWN": Decimal("0.00"),
}

# --- PRD 3.5 acidification -------------------------------------------------
PH_PASS_CEILING = Decimal("4.20")
PH_DOCUMENTABLE_CEILING = Decimal("4.60")
EXPOSURE_PASS_MINUTES = 240
EXPOSURE_DOCUMENTABLE_MINUTES = 300
MAX_TEMP_PASS_C = Decimal("21.0")
VARIANCE_RISK_POINTS = 3

# --- PRD 3.6 fish ----------------------------------------------------------
COLD_LIMIT_C = Decimal("4.4")
QUARANTINE_BREACH_MINUTES = 30
QUARANTINE_RISK_POINTS = 6
FISH_KG_PER_PACK = Decimal("0.045")

# destruction_method -> (minimum temperature ceiling, minimum whole hours)
FREEZE_REGIMES = {
    "FREEZE_MINUS35_15HRS": (Decimal("-35.0"), 15),
    "FREEZE_MINUS35_THEN_MINUS20_24HRS": (Decimal("-35.0"), 24),
    "FREEZE_MINUS20_7DAYS": (Decimal("-20.0"), 168),
}

PARASITE_EXEMPT_SPECIES = ("TUNA_YELLOWFIN", "SHRIMP_COOKED")
PARASITE_EXEMPT_HARVEST = "AQUACULTURE_EXEMPT"

# --- PRD 3.7 packs ---------------------------------------------------------
SHELF_LIFE_MINUTES = 720                  # twelve hours in the case
MARKDOWN_FLOOR_RATE = Decimal("0.30")
MARKDOWN_FLAT_RATE = Decimal("0.50")
CREDIT_ELIGIBLE_REASONS = ("SHELF_LIFE_EXPIRED", "TEMP_ABUSE")
DISCARD_REASONS = (
    "SHELF_LIFE_EXPIRED",
    "TEMP_ABUSE",
    "AUDIT_LOCKDOWN",
    "VARIANCE_REJECTED",
)

# --- PRD 3.8 settlement ----------------------------------------------------
TIER1_CEILING = Decimal("2000000")
TIER2_CEILING = Decimal("5000000")
TIER1_RATE = Decimal("0.12")
TIER2_RATE = Decimal("0.14")
TIER3_RATE = Decimal("0.16")
SPACE_CREDIT_CAP_RATE = Decimal("0.25")
DISCARD_CREDIT_RATE = Decimal("0.40")
DISCARD_CREDIT_CAP_RATE = Decimal("0.10")
MAX_REVISION_ROUND = 3

# --- PRD 3.3 / 3.9 risk and audits ----------------------------------------
FINDING_RISK_POINTS = {"MINOR": 1, "MAJOR": 4, "CRITICAL": 10}
SCORE_DEDUCTIONS = {"MINOR": 2, "MAJOR": 8, "CRITICAL": 20}
CLEAN_AUDIT_CREDIT_PER_AUDIT = 2
RISK_POINTS_MIN = 0
RISK_POINTS_MAX = 40
POSTURE_LOCKDOWN_THRESHOLD = 30
POSTURE_RESTRICTED_THRESHOLD = 18
POSTURE_WATCH_THRESHOLD = 8
AUDIT_MAX_ROUND_COUNT = 2

# --- PRD 3.2 chefs ---------------------------------------------------------
MIN_TRAINING_HOURS = Decimal("24")
MANDATORY_CERT_TYPES = ("FOOD_HANDLER", "HACCP_RICE_ACIDIFICATION")
CERT_TYPES = (
    "FOOD_HANDLER",
    "HACCP_RICE_ACIDIFICATION",
    "PARASITE_DESTRUCTION_VERIFIER",
)


# ==========================================================================
# 1. daily_production_allocation (PRD 3.4)
# ==========================================================================


def daily_production_allocation(traffic_forecast, case_capacity_packs,
                                case_linear_ft, certified_chef_count, posture):
    demand_cap = floor_int(dec(traffic_forecast) * ATTACH_RATE)
    frontage_cap = floor_int(dec(case_linear_ft) * PACKS_PER_LINEAR_FT)
    case_cap = min(int(case_capacity_packs), frontage_cap)
    staffing_cap = floor_int(dec(certified_chef_count) * PACKS_PER_CERTIFIED_CHEF)

    raw_cap = min(demand_cap, case_cap, staffing_cap)
    # Fixed tie-break precedence: DEMAND, then CASE_CAPACITY, then STAFFING.
    if demand_cap == raw_cap:
        binding = "DEMAND"
    elif case_cap == raw_cap:
        binding = "CASE_CAPACITY"
    else:
        binding = "STAFFING"

    factor = POSTURE_FACTORS[posture]
    planned_pack_count = floor_int(dec(raw_cap) * factor)
    planned_rice_kg = round_half_up(dec(planned_pack_count) * RICE_KG_PER_PACK, 2)
    return {
        "demand_cap": demand_cap,
        "case_cap": case_cap,
        "staffing_cap": staffing_cap,
        "raw_cap": raw_cap,
        "binding_cap_source": binding,
        "posture_factor_applied": float(factor),
        "planned_pack_count": planned_pack_count,
        "planned_rice_kg": float(planned_rice_kg),
    }


# ==========================================================================
# 2. rice_acidification_disposition (PRD 3.5)
# ==========================================================================


def rice_acidification_disposition(measured_ph, exposure_minutes, max_temp_c):
    ph = round_half_up(measured_ph, 2)
    temp = round_half_up(max_temp_c, 1)
    ph_ok = ph <= PH_PASS_CEILING
    time_ok = exposure_minutes <= EXPOSURE_PASS_MINUTES
    temp_ok = temp <= MAX_TEMP_PASS_C

    if ph_ok and time_ok and temp_ok:
        return "APPROVED"
    failures = [name for name, ok in
                (("PH", ph_ok), ("TIME", time_ok), ("TEMP", temp_ok)) if not ok]
    if failures == ["PH"] and ph <= PH_DOCUMENTABLE_CEILING:
        return "VARIANCE_REQUIRED"
    if failures == ["TIME"] and exposure_minutes <= EXPOSURE_DOCUMENTABLE_MINUTES:
        return "VARIANCE_REQUIRED"
    return "REJECTED"


# ==========================================================================
# 3. rice_yield_ceiling (PRD 3.5)
# ==========================================================================


def rice_yield_ceiling(rice_kg):
    return floor_int(dec(rice_kg) / RICE_KG_PER_PACK)


# ==========================================================================
# 4. cold_chain_breach_minutes (PRD 3.6)
# ==========================================================================


def interval_breach_minutes(gap_minutes, previous_temp_c, current_temp_c):
    """Three-way per-interval attribution, rounded to a whole minute here --
    before the intervals are summed."""
    prev_hot = round_half_up(previous_temp_c, 1) > COLD_LIMIT_C
    curr_hot = round_half_up(current_temp_c, 1) > COLD_LIMIT_C
    if prev_hot and curr_hot:
        return int(gap_minutes)
    if prev_hot or curr_hot:
        return int(round_half_up(dec(gap_minutes) / Decimal("2"), 0))
    return 0


# ==========================================================================
# 5. parasite_destruction_compliance (PRD 3.6)
# ==========================================================================


def parasite_destruction_required(species, harvest_method):
    if harvest_method == PARASITE_EXEMPT_HARVEST:
        return False
    if species in PARASITE_EXEMPT_SPECIES:
        return False
    return True


def parasite_destruction_compliant(destruction_method, freeze_min_temp_c,
                                   freeze_effective_hours):
    temp_ceiling, min_hours = FREEZE_REGIMES[destruction_method]
    temp_ok = round_half_up(freeze_min_temp_c, 1) <= temp_ceiling
    hours_ok = int(freeze_effective_hours) >= min_hours
    return bool(temp_ok and hours_ok)


# ==========================================================================
# 6. pack_markdown_price (PRD 3.7)
# ==========================================================================


def pack_markdown_price(list_price_cents, remaining_minutes, markdown_policy):
    floor_price = round_cents(dec(list_price_cents) * MARKDOWN_FLOOR_RATE)
    prorated = round_cents(
        dec(list_price_cents) * dec(remaining_minutes) / dec(SHELF_LIFE_MINUTES))
    prorated = max(prorated, floor_price)
    flat = round_cents(dec(list_price_cents) * MARKDOWN_FLAT_RATE)
    flat = max(flat, floor_price)
    if markdown_policy == "PRORATED_REMAINING_LIFE":
        binding, advisory = prorated, flat
    else:
        binding, advisory = flat, prorated
    return {
        "floor_price_cents": floor_price,
        "markdown_price_cents": binding,
        "advisory_markdown_price_cents": advisory,
        "markdown_variant_applied": markdown_policy,
    }


# ==========================================================================
# 7. discard_valuation (PRD 3.7)
# ==========================================================================


def discard_valuation(discarded_count, unit_value_cents, reason):
    return {
        "discarded_count": int(discarded_count),
        "unit_value_cents": int(unit_value_cents),
        "discard_value_cents": int(discarded_count) * int(unit_value_cents),
        "settlement_credit_eligible": reason in CREDIT_ELIGIBLE_REASONS,
    }


# ==========================================================================
# 8. revenue_share_settlement (PRD 3.8)
# ==========================================================================


def tier_ladder(base_cents):
    """Marginal ladder; the three tier products are summed at full precision
    and only the sum is rounded half up to whole cents."""
    base = dec(base_cents)
    if base < 0:
        base = Decimal("0")
    tier1 = min(base, TIER1_CEILING)
    tier2 = min(max(base - TIER1_CEILING, Decimal("0")), TIER2_CEILING - TIER1_CEILING)
    tier3 = max(base - TIER2_CEILING, Decimal("0"))
    total = tier1 * TIER1_RATE + tier2 * TIER2_RATE + tier3 * TIER3_RATE
    return round_cents(total)


def settlement_bases(gross_sales_cents, markdown_sales_cents, revenue_share_model):
    gross = int(gross_sales_cents)
    net = int(gross_sales_cents) - int(markdown_sales_cents)
    if revenue_share_model == "GROSS_SALES":
        return gross, net
    return net, gross


def space_shortfall_credit(space_shortfall_sqft, space_credit_cents_per_sqft,
                           binding_share_cents):
    raw = round_cents(dec(space_shortfall_sqft) * dec(space_credit_cents_per_sqft))
    cap = round_cents(dec(binding_share_cents) * SPACE_CREDIT_CAP_RATE)
    return min(raw, cap)


def discard_credit(eligible_discard_value_cents, binding_share_cents):
    raw = round_cents(dec(eligible_discard_value_cents) * DISCARD_CREDIT_RATE)
    cap = round_cents(dec(binding_share_cents) * DISCARD_CREDIT_CAP_RATE)
    return min(raw, cap)


def net_due(binding_share_cents, space_credit_cents, discard_credit_cents):
    return max(0, int(binding_share_cents) - int(space_credit_cents) - int(discard_credit_cents))


# ==========================================================================
# 9. kiosk_risk_points (PRD 3.3)
# ==========================================================================


def clamp_risk(raw):
    return max(RISK_POINTS_MIN, min(RISK_POINTS_MAX, int(raw)))


def posture_band(risk_points, open_critical_finding_count):
    if int(open_critical_finding_count) > 0:
        return "LOCKDOWN"
    if risk_points >= POSTURE_LOCKDOWN_THRESHOLD:
        return "LOCKDOWN"
    if risk_points >= POSTURE_RESTRICTED_THRESHOLD:
        return "RESTRICTED"
    if risk_points >= POSTURE_WATCH_THRESHOLD:
        return "WATCH"
    return "CLEAR"


# ==========================================================================
# 10. audit_score (PRD 3.9)
# ==========================================================================


def audit_score(findings):
    deduction = 0
    for finding in findings:
        deduction += SCORE_DEDUCTIONS[finding["severity"]]
    return max(0, 100 - deduction)


# ==========================================================================
# 12. plan_forecast_variance (PRD 3.4)
# ==========================================================================


def forecast_variance_pct(planned_pack_count, actual_pack_count):
    if int(planned_pack_count) == 0:
        return float(round_half_up(Decimal("0"), 2))
    value = (dec(actual_pack_count) - dec(planned_pack_count)) * Decimal("100") \
        / dec(planned_pack_count)
    return float(round_half_up(value, 2))


# ==========================================================================
# 13. space_obligation_compliance (PRD 3.1)
# ==========================================================================


def space_shortfall(min_space_sqft_obligation, attested_sqft):
    return max(0, int(min_space_sqft_obligation) - int(attested_sqft))
