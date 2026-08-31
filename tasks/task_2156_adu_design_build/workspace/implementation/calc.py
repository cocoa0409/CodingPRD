"""The six calculation rules of the ADU design-build API."""
from decimal import Decimal

from common import DB, D, by_seq, round_half_up, round_half_up_2, trunc_toward_zero

# ---- feasibility_screening -------------------------------------------------
STATUTORY_ALWAYS_ALLOWED_SQFT = 800
STATUTORY_SETBACK_FT = 4.0
STATUTORY_MAX_HEIGHT_FT = 16.0
AMP_TIER_1_MAX_SQFT = 750
AMP_TIER_2_MAX_SQFT = 1000
EXISTING_DWELLING_LOAD_AMPS = 100
WATER_METER_MIN_IN_SMALL = 0.625
WATER_METER_MIN_IN_LARGE = 0.75

# ---- utility_separation_decision -------------------------------------------
SEPARATION_THRESHOLD = 50
SEPARATE_METER_BASE_CENTS = 850000
SHARED_SUBMETER_CENTS = 220000

# ---- permit_fee_schedule ---------------------------------------------------
TECH_SURCHARGE_PCT = Decimal("0.075")
IMPACT_FEE_EXEMPT_SQFT = 750
SCHOOL_FEE_MIN_SQFT = 500
SCHOOL_FEE_RATE_PER_SQFT_CENTS = 452

# ---- change_order_price_reconciliation -------------------------------------
MARKUP_TIER_1_MAX_PCT = Decimal("5.0")
MARKUP_TIER_2_MAX_PCT = Decimal("15.0")
MARKUP_RATE_TIER_1 = Decimal("0.10")
MARKUP_RATE_TIER_2 = Decimal("0.15")
MARKUP_RATE_TIER_3 = Decimal("0.20")
CHANGE_ORDER_CAP_PCT = Decimal("25.0")

# ---- financing_capacity ----------------------------------------------------
MAX_LTV_PCT = Decimal("0.80")
CAP_RATE = Decimal("0.055")
VACANCY_FACTOR = Decimal("0.92")
EXPENSE_RATIO = Decimal("0.35")
SOFT_COST_CONTINGENCY_PCT = Decimal("0.10")

# ---- rental_readiness_check ------------------------------------------------
STATE_MIN_ADU_LEASE_DAYS = 30
STR_PERMITTED_MAX_LEASE_DAYS = 7

# ---- construction sequencing ----------------------------------------------
MAX_SHUTOFF_DAYS_OCCUPIED = 1
HABITABILITY_BUFFER_DAYS = 2


def required_service_amps(proposed_sqft):
    if proposed_sqft <= AMP_TIER_1_MAX_SQFT:
        return 100
    if proposed_sqft <= AMP_TIER_2_MAX_SQFT:
        return 125
    return 200


# ---------------------------------------------------------------------------
# 1. feasibility screening
# ---------------------------------------------------------------------------
def feasibility_screening(project, prop, jur, pathway):
    if pathway == "LOCAL_ORDINANCE":
        max_allowed_sqft = jur["local_max_detached_sqft"]
        req_rear = jur["local_rear_setback_ft"]
        req_side = jur["local_side_setback_ft"]
        req_height = jur["local_max_height_ft"]
    else:  # STATUTORY_MINISTERIAL
        max_allowed_sqft = max(STATUTORY_ALWAYS_ALLOWED_SQFT, jur["local_max_detached_sqft"])
        if project["unit_type"] in ("CONVERSION", "JADU"):
            req_rear = 0.0
            req_side = 0.0
        else:
            req_rear = STATUTORY_SETBACK_FT
            req_side = STATUTORY_SETBACK_FT
        req_height = STATUTORY_MAX_HEIGHT_FT

    sqft = project["proposed_sqft"]
    amps = required_service_amps(sqft)
    min_meter = (
        WATER_METER_MIN_IN_LARGE if sqft >= STATUTORY_ALWAYS_ALLOWED_SQFT
        else WATER_METER_MIN_IN_SMALL
    )

    zoning_ok = sqft <= max_allowed_sqft
    setback_ok = (
        D(project["rear_setback_ft"]) >= D(req_rear)
        and D(project["side_setback_ft"]) >= D(req_side)
    )
    height_ok = D(project["proposed_height_ft"]) <= D(req_height)
    utility_capacity_ok = (
        prop["electrical_service_amps"] >= amps + EXISTING_DWELLING_LOAD_AMPS
        and D(prop["existing_water_meter_size_in"]) >= D(min_meter)
    )

    deficiency_codes = sorted(
        code
        for code, okflag in (
            ("HEIGHT", height_ok),
            ("SETBACK", setback_ok),
            ("UTILITY_CAPACITY", utility_capacity_ok),
            ("ZONING", zoning_ok),
        )
        if not okflag
    )

    if not (zoning_ok and setback_ok and height_ok):
        verdict = "FAIL"
    elif not utility_capacity_ok:
        verdict = "PASS_WITH_CONDITIONS"
    else:
        verdict = "PASS"

    return {
        "max_allowed_sqft": max_allowed_sqft,
        "required_rear_setback_ft": req_rear,
        "required_side_setback_ft": req_side,
        "required_height_ft": req_height,
        "required_service_amps": amps,
        "zoning_ok": zoning_ok,
        "setback_ok": setback_ok,
        "height_ok": height_ok,
        "utility_capacity_ok": utility_capacity_ok,
        "verdict": verdict,
        "deficiency_codes": deficiency_codes,
    }


# ---------------------------------------------------------------------------
# 2. utility separation decision
# ---------------------------------------------------------------------------
def utility_separation_decision(project, prop, jur, override_decision):
    amps = required_service_amps(project["proposed_sqft"])
    headroom_amps = prop["electrical_service_amps"] - amps - EXISTING_DWELLING_LOAD_AMPS
    water_headroom = 1 if D(prop["existing_water_meter_size_in"]) >= D(1.0) else 0

    raw = (
        40 * (1 if jur["separate_meter_required"] else 0)
        + 25 * (1 if headroom_amps < 0 else 0)
        + 20 * (1 if project["unit_type"] == "DETACHED_NEW" else 0)
        + 15 * (1 if project["bedrooms"] >= 2 else 0)
        - 10 * water_headroom
    )
    separation_score = max(0, min(100, raw))

    if override_decision is not None:
        decision = override_decision
    else:
        decision = "SEPARATE" if separation_score >= SEPARATION_THRESHOLD else "SHARED"

    if decision == "SEPARATE":
        cost = jur["utility_capacity_fee_cents"] + SEPARATE_METER_BASE_CENTS
    else:
        cost = SHARED_SUBMETER_CENTS

    return separation_score, decision, cost


# ---------------------------------------------------------------------------
# 3. permit fee schedule
# ---------------------------------------------------------------------------
def permit_fee_schedule(project, prop, jur):
    sqft = project["proposed_sqft"]

    plan_check = round_half_up(
        (D(jur["plan_check_base_fee_cents"]) + D(jur["plan_check_rate_per_sqft_cents"]) * D(sqft))
        * (Decimal("1") + TECH_SURCHARGE_PCT)
    )

    if sqft < IMPACT_FEE_EXEMPT_SQFT:
        impact = 0
    else:
        ratio = D(sqft) / D(prop["existing_dwelling_sqft"])
        factor = ratio if ratio < Decimal("1.0") else Decimal("1.0")
        impact = round_half_up(D(jur["impact_fee_per_sqft_cents"]) * D(sqft) * factor)

    if sqft < SCHOOL_FEE_MIN_SQFT:
        school = 0
    else:
        school = round_half_up(
            D(SCHOOL_FEE_RATE_PER_SQFT_CENTS) * D(sqft) * (Decimal("1") + TECH_SURCHARGE_PCT)
        )

    utility = 0
    for uc in by_seq(
        [u for u in DB.utilities.values() if u["adu_project_id"] == project["id"]]
    ):
        if uc["status"] in ("SEPARATE_APPROVED", "SHARED_APPROVED", "ENERGIZED"):
            utility += uc["separation_cost_cents"]

    return {
        "plan_check_component_cents": plan_check,
        "impact_component_cents": impact,
        "school_component_cents": school,
        "utility_component_cents": utility,
        "total_permit_fee_cents": plan_check + impact + school + utility,
    }


# ---------------------------------------------------------------------------
# 4. change order price reconciliation
# ---------------------------------------------------------------------------
def approved_change_orders(project_id, exclude_id=None):
    rows = [
        co
        for co in DB.change_orders.values()
        if co["adu_project_id"] == project_id
        and co["status"] == "APPROVED"
        and (exclude_id is None or co["id"] != exclude_id)
    ]
    return by_seq(rows)


def change_order_reconciliation(project, change_order):
    """Returns (builder_fee_cents, pct_before, pct_after, new_contract_price)."""
    base = D(project["contract_base_price_cents"])
    cumulative_prior = 0
    for co in approved_change_orders(project["id"], exclude_id=change_order["id"]):
        cumulative_prior += co["cost_delta_cents"] + co["builder_fee_cents"]

    pct_before = round_half_up_2(Decimal("100") * D(cumulative_prior) / base)

    pb = D(pct_before)
    if pb < MARKUP_TIER_1_MAX_PCT:
        markup_rate = MARKUP_RATE_TIER_1
    elif pb < MARKUP_TIER_2_MAX_PCT:
        markup_rate = MARKUP_RATE_TIER_2
    else:
        markup_rate = MARKUP_RATE_TIER_3

    builder_fee = round_half_up(D(change_order["cost_delta_cents"]) * markup_rate)

    new_price = int(
        project["contract_base_price_cents"]
        + cumulative_prior
        + change_order["cost_delta_cents"]
        + builder_fee
    )

    pct_after = round_half_up_2(
        Decimal("100")
        * D(cumulative_prior + change_order["cost_delta_cents"] + builder_fee)
        / base
    )

    return builder_fee, pct_before, pct_after, new_price


def recompute_contract_price(project):
    total = project["contract_base_price_cents"]
    for co in approved_change_orders(project["id"]):
        total += co["cost_delta_cents"] + co["builder_fee_cents"]
    return int(total)


# ---------------------------------------------------------------------------
# 5. financing capacity
# ---------------------------------------------------------------------------
def financing_capacity(scenario, project, prop):
    if scenario["appraisal_approach"] == "SALES_COMPARISON":
        as_completed = int(prop["pre_adu_value_cents"] + scenario["comparable_adjustment_cents"])
    else:
        capitalized = round_half_up(
            (
                D(scenario["projected_monthly_rent_cents"])
                * Decimal("12")
                * VACANCY_FACTOR
                * (Decimal("1") - EXPENSE_RATIO)
            )
            / CAP_RATE
        )
        as_completed = int(prop["pre_adu_value_cents"] + capitalized)

    max_loan = trunc_toward_zero(D(as_completed) * MAX_LTV_PCT)
    available = int(max_loan - prop["existing_mortgage_balance_cents"])

    required_funds = int(
        project["contract_price_current_cents"]
        + project["total_permit_fee_cents"]
        + round_half_up(D(project["contract_price_current_cents"]) * SOFT_COST_CONTINGENCY_PCT)
    )

    funding_gap = max(0, required_funds - available)
    appraisal_shortfall = (as_completed - prop["pre_adu_value_cents"]) < required_funds

    return {
        "as_completed_value_cents": as_completed,
        "max_loan_cents": max_loan,
        "available_cents": available,
        "required_funds_cents": required_funds,
        "funding_gap_cents": funding_gap,
        "appraisal_shortfall": appraisal_shortfall,
    }


# ---------------------------------------------------------------------------
# 6. rental readiness check
# ---------------------------------------------------------------------------
def rental_readiness_check(project, prop, jur):
    blocking = []
    if project["unit_type"] == "JADU" and prop["occupied"] is False:
        blocking.append("JADU_OWNER_OCCUPANCY_REQUIRED")
    open_cos = [
        co
        for co in DB.change_orders.values()
        if co["adu_project_id"] == project["id"]
        and co["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED")
    ]
    if len(open_cos) > 0:
        blocking.append("OPEN_CHANGE_ORDERS")
    if prop["in_str_overlay"] or jur["str_prohibited"]:
        blocking.append("STR_OVERLAY_RESTRICTED")
    blocking_reasons = sorted(blocking)

    str_min = jur["str_min_lease_days"]
    if "JADU_OWNER_OCCUPANCY_REQUIRED" in blocking_reasons:
        rental_classification = "RENTAL_PROHIBITED"
        min_lease_days = max(STATE_MIN_ADU_LEASE_DAYS, str_min)
    elif "STR_OVERLAY_RESTRICTED" in blocking_reasons:
        rental_classification = "LONG_TERM_ONLY"
        min_lease_days = max(STATE_MIN_ADU_LEASE_DAYS, str_min)
    elif str_min <= STR_PERMITTED_MAX_LEASE_DAYS:
        rental_classification = "SHORT_TERM_PERMITTED"
        min_lease_days = str_min
    else:
        rental_classification = "LONG_TERM_ONLY"
        min_lease_days = max(STATE_MIN_ADU_LEASE_DAYS, str_min)

    rental_ready = rental_classification != "RENTAL_PROHIBITED" and len(blocking_reasons) == 0

    return {
        "rental_classification": rental_classification,
        "min_lease_days": min_lease_days,
        "rental_ready": rental_ready,
        "blocking_reasons": blocking_reasons,
    }
