"""The nine derivations of PRD 2.11 / 3.  Every rounding is ROUND_HALF_UP and
every pinned evaluation or accumulation order is honoured literally."""

from decimal import Decimal

from common import D, ZERO, HUNDRED, add_days, add_years_date, dmax, dmin, q2, q4

# --- owner capacity scoring -------------------------------------------------
LIQUIDITY_BENCHMARK = Decimal("5000000.00")
NET_WORTH_BENCHMARK = Decimal("15000000.00")
CREDIT_FLOOR = Decimal("500")
CREDIT_SPAN = Decimal("300")
EXISTING_UNIT_RESERVE = Decimal("250000.00")
PORTFOLIO_EXPERIENCE_POINTS = Decimal("1.5")
EXPERIENCE_CAP_UNITS = 5
W_LIQUIDITY = Decimal("0.45")
W_NET_WORTH = Decimal("0.30")
W_CREDIT = Decimal("0.25")
CAPACITY_BAND_STRONG = Decimal("75.00")
CAPACITY_BAND_ADEQUATE = Decimal("55.00")

# --- market impact ----------------------------------------------------------
IMPACT_SCALE_POINTS = Decimal("100.00")
CLAIM_PENALTY_POINTS = Decimal("7.50")
ENCROACHMENT_CONFIRMED_THRESHOLD = Decimal("25.00")
MITIGATION_THRESHOLD = Decimal("12.00")
CLAIM_WINDOW_DAYS = 21

# --- license terms ----------------------------------------------------------
CONVERSION_ADJUSTMENT = {
    "COMPETITOR": Decimal("0.75"),
    "INDEPENDENT": Decimal("0.25"),
    "OUR_BRAND": Decimal("0.00"),
}
CAPACITY_DISCOUNT_DEEP = Decimal("0.50")
CAPACITY_DISCOUNT_BASE = Decimal("0.25")
PORTFOLIO_DISCOUNT_UNITS = 3
BRAND_MAX_ROYALTY = Decimal("7.00")
BRAND_MIN_ROYALTY = Decimal("3.50")
MARKETING_IMPACT_SURCHARGE = Decimal("0.50")
MARKETING_FUND_CEILING = Decimal("3.00")
TERM_FLOOR_YEARS = 15

# --- monthly fees -----------------------------------------------------------
TIER1_CAP = Decimal("200000.00")
TIER2_CAP = Decimal("500000.00")
TIER2_PREMIUM_PCT = Decimal("0.50")
TIER3_PREMIUM_PCT = Decimal("1.00")
RESERVATION_FEE_RATE_PCT = Decimal("1.75")

# --- liquidated damages -----------------------------------------------------
DISCOUNT_RATE_MONTHLY = Decimal("0.0050")
LD_CAP_MONTHS = 36

# --- quality assurance ------------------------------------------------------
W_CLEANLINESS = Decimal("0.30")
W_CONDITION = Decimal("0.25")
W_BRAND_STANDARD = Decimal("0.30")
W_GUEST_EXPERIENCE = Decimal("0.15")
CRITICAL_DEFECT_PENALTY_POINTS = Decimal("5.00")
QA_PASS_THRESHOLD = Decimal("85.00")
QA_CONDITIONAL_THRESHOLD = Decimal("70.00")
CURE_DAYS_CONDITIONAL = 60
CURE_DAYS_FAIL = 30
QA_FAILURE_TERMINATION_THRESHOLD = 3
MIN_INSPECTION_GAP_DAYS = 90

# --- improvement plan -------------------------------------------------------
KEY_MONEY_BAND_HIGH = Decimal("25000.00")
KEY_MONEY_BAND_MID = Decimal("12000.00")
KEY_MONEY_PCT_HIGH = 10
KEY_MONEY_PCT_MID = 6
KEY_MONEY_CAP = Decimal("250000.00")
COST_PER_ROOM_CEILING = Decimal("20000.00")
PRIORITY_DAYS = {"CRITICAL": 90, "MAJOR": 180, "MINOR": 270}
CATEGORY_DAYS = {
    "LIFE_SAFETY": 45,
    "TECHNOLOGY": 120,
    "FOOD_BEVERAGE": 180,
    "GUESTROOM": 210,
    "EXTERIOR": 240,
}
MAX_EXTENSION_DAYS_PER_ITEM = 60
MAX_EXTENSION_REQUESTS_PER_ITEM = 2
PIP_EXTENSION_POOL_DAYS = 120
PIP_DEFAULT_CURE_DAYS = 30
DE_IDENTIFICATION_DAYS = 30
DE_IDENTIFICATION_BREACH_PENALTY = Decimal("50000.00")

# --- consent fees -----------------------------------------------------------
TRANSFER_FEE_MIN = Decimal("75000.00")
TRANSFER_FEE_PER_ROOM = Decimal("750.00")
CHANGE_OF_CONTROL_FACTOR = Decimal("0.50")
REFINANCE_CONSENT_FEE = Decimal("15000.00")
NON_COMPLIANCE_SURCHARGE = Decimal("25000.00")

DE_IDENTIFICATION_ITEMS = (
    "SIGNAGE",
    "INTERIOR_BRANDING",
    "DIGITAL_LISTINGS",
    "LINENS_AND_COLLATERAL",
    "RESERVATION_CODES",
)


# ===========================================================================
# 1. owner_capacity_score  (variants STANDALONE / PORTFOLIO_ADJUSTED)
# ===========================================================================


def capacity_band(score):
    if score >= CAPACITY_BAND_STRONG:
        return "STRONG"
    if score >= CAPACITY_BAND_ADEQUATE:
        return "ADEQUATE"
    return "INSUFFICIENT"


def owner_capacity_score(owner, variant):
    liquid = D(owner["liquid_assets_amount"])
    units = int(owner["existing_units_count"])
    if variant == "PORTFOLIO_ADJUSTED":
        liquid_effective = dmax(ZERO, liquid - EXISTING_UNIT_RESERVE * units)
    else:
        liquid_effective = liquid
    liquidity_component = dmin(HUNDRED, q2(liquid_effective / LIQUIDITY_BENCHMARK * 100))
    net_worth_component = dmin(
        HUNDRED, q2(D(owner["net_worth_amount"]) / NET_WORTH_BENCHMARK * 100)
    )
    credit_component = dmin(
        HUNDRED,
        dmax(ZERO, q2((D(owner["credit_score"]) - CREDIT_FLOOR) / CREDIT_SPAN * 100)),
    )
    weighted_subtotal = q2(
        liquidity_component * W_LIQUIDITY
        + net_worth_component * W_NET_WORTH
        + credit_component * W_CREDIT
    )
    if variant == "PORTFOLIO_ADJUSTED":
        experience_bonus = q2(
            PORTFOLIO_EXPERIENCE_POINTS * min(units, EXPERIENCE_CAP_UNITS)
        )
    else:
        experience_bonus = ZERO
    score = dmin(HUNDRED, q2(weighted_subtotal + experience_bonus))
    return score


def recompute_owner_capacity(owner):
    standalone = owner_capacity_score(owner, "STANDALONE")
    portfolio = owner_capacity_score(owner, "PORTFOLIO_ADJUSTED")
    owner["capacity_score_standalone"] = standalone
    owner["capacity_band_standalone"] = capacity_band(standalone)
    owner["capacity_score_portfolio_adjusted"] = portfolio
    owner["capacity_band_portfolio_adjusted"] = capacity_band(portfolio)


def owner_score_for_basis(owner, basis):
    if basis == "PORTFOLIO_ADJUSTED":
        return owner["capacity_score_portfolio_adjusted"], owner[
            "capacity_band_portfolio_adjusted"
        ]
    return owner["capacity_score_standalone"], owner["capacity_band_standalone"]


# ===========================================================================
# 2. market_impact_score  (variants PRELIMINARY / FINAL)
# ===========================================================================


def unit_distance(unit, application):
    dx = D(unit["x_miles"]) - D(application["property_x_miles"])
    dy = D(unit["y_miles"]) - D(application["property_y_miles"])
    return q2((dx * dx + dy * dy).sqrt())


def market_impact_score(application, brand, units):
    """`units` must already arrive in ascending created_at order."""
    radius = D(brand["protected_radius_miles"])
    rooms = D(application["room_count"])
    admitted = []
    total = ZERO
    for unit in units:
        distance = unit_distance(unit, application)
        if distance > radius:
            continue
        admitted.append(unit)
        proximity_factor = q4((radius - distance) / radius)
        room_share = q4(rooms / (rooms + D(unit["room_count"])))
        total = total + q2(IMPACT_SCALE_POINTS * proximity_factor * room_share)
    raw_score = q2(total)
    return dmin(HUNDRED, raw_score), len(admitted)


def encroachment_verdict(final_score):
    if final_score >= ENCROACHMENT_CONFIRMED_THRESHOLD:
        return "ENCROACHMENT_CONFIRMED"
    if final_score >= MITIGATION_THRESHOLD:
        return "MITIGATION_REQUIRED"
    return "CLEAR"


def final_impact_score(base_score, sustained_claim_count):
    return dmin(
        HUNDRED, q2(D(base_score) + CLAIM_PENALTY_POINTS * int(sustained_claim_count))
    )


# ===========================================================================
# 3. license_terms_derivation
# ===========================================================================


def license_terms(application, brand, owner, effective_date):
    conversion_adjustment = CONVERSION_ADJUSTMENT[application["current_affiliation"]]
    band = application.get("capacity_band_at_review")
    if band == "STRONG" and int(owner["existing_units_count"]) >= PORTFOLIO_DISCOUNT_UNITS:
        capacity_discount = CAPACITY_DISCOUNT_DEEP
    elif band == "STRONG":
        capacity_discount = CAPACITY_DISCOUNT_BASE
    else:
        capacity_discount = ZERO
    raw_royalty = (
        D(brand["base_royalty_rate_pct"]) + conversion_adjustment - capacity_discount
    )
    royalty_rate_pct = q2(dmin(BRAND_MAX_ROYALTY, dmax(BRAND_MIN_ROYALTY, raw_royalty)))

    final_score = application.get("final_impact_score")
    surcharge = (
        MARKETING_IMPACT_SURCHARGE
        if final_score is not None and D(final_score) >= MITIGATION_THRESHOLD
        else ZERO
    )
    marketing_fund_rate_pct = q2(
        dmin(MARKETING_FUND_CEILING, D(brand["marketing_fund_rate_pct"]) + surcharge)
    )

    term_years = min(
        int(brand["standard_term_years"]),
        max(TERM_FLOOR_YEARS, int(application["requested_term_years"])),
    )
    expiry_date = add_years_date(effective_date, term_years)
    return royalty_rate_pct, marketing_fund_rate_pct, term_years, expiry_date


# ===========================================================================
# 4. monthly_fee_assessment
# ===========================================================================


def monthly_fees(gross, royalty_rate, marketing_rate):
    gross = D(gross)
    royalty_rate = D(royalty_rate)
    marketing_rate = D(marketing_rate)
    tier1_base = dmin(gross, TIER1_CAP)
    tier2_base = dmax(ZERO, dmin(gross, TIER2_CAP) - TIER1_CAP)
    tier3_base = dmax(ZERO, gross - TIER2_CAP)
    royalty_fee = (
        q2(tier1_base * royalty_rate / 100)
        + q2(tier2_base * (royalty_rate + TIER2_PREMIUM_PCT) / 100)
        + q2(tier3_base * (royalty_rate + TIER3_PREMIUM_PCT) / 100)
    )
    marketing_fee = q2(gross * marketing_rate / 100)
    reservation_fee = q2(gross * RESERVATION_FEE_RATE_PCT / 100)
    period_total_fee = royalty_fee + marketing_fee + reservation_fee
    return royalty_fee, marketing_fee, reservation_fee, period_total_fee


def recompute_ledger(agreement):
    royalty = ZERO
    marketing = ZERO
    reservation = ZERO
    total = ZERO
    count = 0
    for entry in agreement["revenue_periods"]:
        if entry["superseded"]:
            continue
        royalty = royalty + D(entry["royalty_fee"])
        marketing = marketing + D(entry["marketing_fee"])
        reservation = reservation + D(entry["reservation_fee"])
        total = total + D(entry["period_total_fee"])
        count += 1
    agreement["royalty_fee_to_date"] = royalty
    agreement["marketing_fund_contributed_total"] = marketing
    agreement["reservation_fee_to_date"] = reservation
    agreement["total_fees_assessed"] = total
    agreement["reported_period_count"] = count


# ===========================================================================
# 5. liquidated_damages  (variants CONTRACTUAL_MULTIPLE / DISCOUNTED_PV)
# ===========================================================================


def trailing_average_fee(agreement):
    basis = ZERO
    count = 0
    for entry in agreement["revenue_periods"]:
        if entry["superseded"]:
            continue
        basis = basis + D(entry["royalty_fee"]) + D(entry["marketing_fee"])
        count += 1
    if count == 0:
        return ZERO
    return q2(basis / count)


def liquidated_damages(formula, trailing_avg, capped_months):
    if capped_months <= 0:
        return ZERO
    if formula == "CONTRACTUAL_MULTIPLE":
        return q2(D(trailing_avg) * capped_months)
    total = ZERO
    for k in range(1, capped_months + 1):
        divisor = (Decimal(1) + DISCOUNT_RATE_MONTHLY) ** k
        total = total + q2(D(trailing_avg) / divisor)
    return total


# ===========================================================================
# 6. qa_inspection_score
# ===========================================================================


def qa_scores(cleanliness, condition, brand_standard, guest_experience, defects, life_safety):
    weighted = q2(
        D(cleanliness) * W_CLEANLINESS
        + D(condition) * W_CONDITION
        + D(brand_standard) * W_BRAND_STANDARD
        + D(guest_experience) * W_GUEST_EXPERIENCE
    )
    total = q2(dmax(ZERO, weighted - CRITICAL_DEFECT_PENALTY_POINTS * int(defects)))
    if life_safety:
        grade = "FAIL"
    elif total >= QA_PASS_THRESHOLD:
        grade = "PASS"
    elif total >= QA_CONDITIONAL_THRESHOLD:
        grade = "CONDITIONAL"
    else:
        grade = "FAIL"
    if grade == "PASS":
        cure_days = None
    elif grade == "CONDITIONAL":
        cure_days = CURE_DAYS_CONDITIONAL
    else:
        cure_days = CURE_DAYS_FAIL
    return weighted, total, grade, cure_days


# ===========================================================================
# 7. pip_cost_allocation
# ===========================================================================


def pip_total_cost(items):
    total = ZERO
    for item in items:
        total = total + D(item["estimated_cost"])
    return q2(total)


def pip_cost_allocation(total_estimated_cost, room_count):
    total_estimated_cost = D(total_estimated_cost)
    rooms = D(room_count)
    cost_per_room = q2(total_estimated_cost / rooms)
    if cost_per_room >= KEY_MONEY_BAND_HIGH:
        key_money_pct = KEY_MONEY_PCT_HIGH
    elif cost_per_room >= KEY_MONEY_BAND_MID:
        key_money_pct = KEY_MONEY_PCT_MID
    else:
        key_money_pct = 0
    franchisor_key_money = dmin(
        KEY_MONEY_CAP, q2(total_estimated_cost * key_money_pct / 100)
    )
    owner_net_cost = total_estimated_cost - franchisor_key_money
    owner_net_cost_per_room = q2(owner_net_cost / rooms)
    escalation_required = owner_net_cost_per_room > COST_PER_ROOM_CEILING
    return {
        "cost_per_room": cost_per_room,
        "key_money_pct": key_money_pct,
        "franchisor_key_money": franchisor_key_money,
        "owner_net_cost": owner_net_cost,
        "owner_net_cost_per_room": owner_net_cost_per_room,
        "escalation_required": escalation_required,
    }


# ===========================================================================
# 8. pip_item_deadline
# ===========================================================================


def item_allowance_days(item):
    return min(PRIORITY_DAYS[item["priority"]], CATEGORY_DAYS[item["category"]])


def grant_days(requested_days, item_granted_total, pip_granted_total):
    candidate = min(
        int(requested_days),
        MAX_EXTENSION_DAYS_PER_ITEM - int(item_granted_total),
        PIP_EXTENSION_POOL_DAYS - int(pip_granted_total),
    )
    return max(0, candidate)


# ===========================================================================
# 9. transfer_consent_fee
# ===========================================================================


def consent_fees(request_type, room_count, compliance_status):
    per_room_fee = q2(D(room_count) * TRANSFER_FEE_PER_ROOM)
    base_fee = dmax(TRANSFER_FEE_MIN, per_room_fee)
    if request_type == "TRANSFER":
        transfer_fee = base_fee
    elif request_type == "CHANGE_OF_CONTROL":
        transfer_fee = q2(base_fee * CHANGE_OF_CONTROL_FACTOR)
    else:
        transfer_fee = REFINANCE_CONSENT_FEE
    surcharge = NON_COMPLIANCE_SURCHARGE if compliance_status != "COMPLIANT" else ZERO
    return transfer_fee, surcharge, transfer_fee + surcharge
