"""Every derived quantity in the system (PRD sections 2.6, 3.2, 3.3, 3.7-3.9).

All money is whole cents. Every monetary component is rounded half-up to whole
cents at the step that produces it, never deferred and never accumulated.
"""

from decimal import Decimal, ROUND_HALF_UP

import store

ZERO = Decimal("0")

# hazard tiers, worst-governs total order
TIER_ORDER = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}
HAZARD_BASE_PCT = {"T1": Decimal("0.025"), "T2": Decimal("0.070"),
                   "T3": Decimal("0.135"), "T4": Decimal("0.205")}
MULTI_JURISDICTION_SPREAD_PCT = Decimal("0.010")
HAZARD_LOAD_CAP_PCT = Decimal("0.30")

RISK_CREDIT_CAP_PCT = Decimal("0.15")

HAZARD_POINTS = {"T1": Decimal("5"), "T2": Decimal("12"),
                 "T3": Decimal("20"), "T4": Decimal("28")}
MULTI_JURISDICTION_POINTS_PER_EXTRA = Decimal("2.00")
MULTI_JURISDICTION_POINTS_CAP = Decimal("8.00")
TURNOVER_POINTS_FACTOR = Decimal("0.80")
TURNOVER_POINTS_CAP = Decimal("30.00")
SERVICE_SCORE_CREDIT = {"HOTLINE_SUBSCRIPTION": Decimal("6.00"),
                        "HANDBOOK_REVIEW": Decimal("4.00"),
                        "MANAGER_TRAINING": Decimal("3.00")}
EXPOSURE_SCORE_MIN = Decimal("0.00")
EXPOSURE_SCORE_MAX = Decimal("100.00")
REFERRAL_SCORE_THRESHOLD = Decimal("72.00")

LIMIT_REFERENCE_CENTS = Decimal("100000000")
LIMIT_LOAD_FACTOR_RATE = Decimal("0.10")

PARTNER_RATE_CAP_CENTS = 75000
ASSOCIATE_RATE_CAP_CENTS = 45000
BLOCK_BILLING_REDUCTION_PCT = Decimal("0.20")
EXPENSE_CAP_PCT = Decimal("0.08")

WAGE_HOUR_RETENTION_MULTIPLIER = Decimal("1.50")
THIRD_PARTY_RETENTION_MULTIPLIER = Decimal("1.25")

PRE_SUIT_CREDIT_PCT = Decimal("0.30")
PRE_SUIT_CREDIT_CAP_CENTS = 750000

SERVICE_GAP_BUFFER_DAYS = 30
REOPEN_LIMIT = 1

BLENDED_PARTNER_WEIGHT = Decimal("0.35")
BLENDED_ASSOCIATE_WEIGHT = Decimal("0.50")
BLENDED_PARALEGAL_WEIGHT = Decimal("0.15")


def round_cents(value):
    """Round-half-up to a whole number of cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q3(value):
    return Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# applicant derived values
# --------------------------------------------------------------------------
def turnover_pct(separations, total_headcount):
    if total_headcount <= 0:
        return q2(ZERO)
    return q2(Decimal(separations) * Decimal(100) / Decimal(total_headcount))


def governing_tier(applicant):
    worst = None
    for entry in applicant["jurisdiction_headcounts"]:
        row = store.jurisdiction_by_code(entry["code"])
        if row is None:
            continue
        tier = row["hazard_tier"]
        if worst is None or TIER_ORDER[tier] > TIER_ORDER[worst]:
            worst = tier
    return worst


def hazard_load_pct(applicant):
    tier = governing_tier(applicant)
    count = len(applicant["jurisdiction_headcounts"])
    base = HAZARD_BASE_PCT.get(tier, ZERO)
    spread = MULTI_JURISDICTION_SPREAD_PCT * Decimal(max(0, count - 1))
    total = base + spread
    if total > HAZARD_LOAD_CAP_PCT:
        total = HAZARD_LOAD_CAP_PCT
    return q3(total)


def risk_credit_pct(services):
    total = ZERO
    for service in services:
        if service["status"] == "ACTIVE":
            total += service["credit_pct"]
    if total > RISK_CREDIT_CAP_PCT:
        total = RISK_CREDIT_CAP_PCT
    return q2(total)


def headcount_band_points(total_headcount):
    if total_headcount <= 50:
        return Decimal("8")
    if total_headcount <= 250:
        return Decimal("16")
    if total_headcount <= 1000:
        return Decimal("26")
    return Decimal("34")


def exposure_score(applicant, services):
    points = headcount_band_points(applicant["total_headcount"])
    tier = governing_tier(applicant)
    count = len(applicant["jurisdiction_headcounts"])
    points += HAZARD_POINTS.get(tier, ZERO)
    extra = MULTI_JURISDICTION_POINTS_PER_EXTRA * Decimal(max(0, count - 1))
    if extra > MULTI_JURISDICTION_POINTS_CAP:
        extra = MULTI_JURISDICTION_POINTS_CAP
    points += extra
    turnover_points = q2(applicant["turnover_pct"] * TURNOVER_POINTS_FACTOR)
    if turnover_points > TURNOVER_POINTS_CAP:
        turnover_points = TURNOVER_POINTS_CAP
    points += turnover_points
    for service in services:
        if service["status"] == "ACTIVE":
            points -= SERVICE_SCORE_CREDIT[service["service_type"]]
    if points < EXPOSURE_SCORE_MIN:
        points = EXPOSURE_SCORE_MIN
    if points > EXPOSURE_SCORE_MAX:
        points = EXPOSURE_SCORE_MAX
    return q2(points)


# --------------------------------------------------------------------------
# premium
# --------------------------------------------------------------------------
def headcount_volume_factor(total_headcount):
    if total_headcount <= 50:
        return Decimal("1.000")
    if total_headcount <= 250:
        return Decimal("0.925")
    if total_headcount <= 1000:
        return Decimal("0.855")
    return Decimal("0.785")


def turnover_load_pct(turnover):
    if turnover >= Decimal("35.00"):
        return Decimal("0.25")
    if turnover >= Decimal("20.00"):
        return Decimal("0.14")
    if turnover >= Decimal("10.00"):
        return Decimal("0.06")
    return Decimal("0.00")


def retention_credit_pct(retention_cents):
    if retention_cents >= 10000000:
        return Decimal("0.11")
    if retention_cents >= 2500000:
        return Decimal("0.05")
    return Decimal("0.00")


def limit_load_factor(requested_limit_cents):
    factor = (Decimal(requested_limit_cents) / LIMIT_REFERENCE_CENTS
              - Decimal(1)) * LIMIT_LOAD_FACTOR_RATE
    if factor < ZERO:
        return ZERO
    return factor


def indicated_premium(plan, applicant, requested_limit_cents,
                      requested_retention_cents, turnover_basis_pct,
                      risk_credit_basis_pct):
    """The eight pinned steps of PRD section 3.3. Returns a dict of components."""
    factor = headcount_volume_factor(applicant["total_headcount"])
    per_employee = Decimal(plan["base_rate_per_employee_cents"]) * factor
    base = 0
    for entry in sorted(applicant["jurisdiction_headcounts"],
                        key=lambda e: e["code"]):
        base += round_cents(Decimal(entry["headcount"]) * per_employee)
    turnover_load = round_cents(Decimal(base)
                                * turnover_load_pct(turnover_basis_pct))
    hazard_load = round_cents(Decimal(base) * applicant["hazard_load_pct"])
    limit_load = round_cents(Decimal(base)
                             * limit_load_factor(requested_limit_cents))
    retention_credit = round_cents(
        Decimal(base) * retention_credit_pct(requested_retention_cents))
    gross = base + turnover_load + hazard_load + limit_load
    risk_credit = round_cents(Decimal(gross) * risk_credit_basis_pct)
    net = gross - retention_credit - risk_credit
    result = max(net, plan["min_premium_cents"])
    return {
        "base_premium_cents": base,
        "turnover_load_cents": turnover_load,
        "hazard_load_cents": hazard_load,
        "limit_load_cents": limit_load,
        "retention_credit_cents": retention_credit,
        "risk_mgmt_credit_cents": risk_credit,
        "gross_premium_cents": gross,
        "net_premium_cents": net,
        "indicated_premium_cents": result,
    }


# --------------------------------------------------------------------------
# claims / defense / settlement
# --------------------------------------------------------------------------
def coverage_bucket(claim_type, claimant_class):
    if claim_type == "WAGE_AND_HOUR":
        return "WAGE_HOUR"
    if claimant_class in ("CUSTOMER", "VENDOR"):
        return "THIRD_PARTY"
    return "FIRST_PARTY"


def claim_retention_cents(policy_base_cents, claim_type, claimant_class):
    multiplier = Decimal("1.00")
    if claim_type == "WAGE_AND_HOUR":
        multiplier *= WAGE_HOUR_RETENTION_MULTIPLIER
    if claimant_class in ("CUSTOMER", "VENDOR"):
        multiplier *= THIRD_PARTY_RETENTION_MULTIPLIER
    return round_cents(Decimal(policy_base_cents) * multiplier)


def pre_suit_incentive_credit_cents(settlement_offer_cents):
    credit = round_cents(Decimal(settlement_offer_cents) * PRE_SUIT_CREDIT_PCT)
    return min(credit, PRE_SUIT_CREDIT_CAP_CENTS)


def blended_rate_cents(partner, associate, paralegal):
    return round_cents(Decimal(partner) * BLENDED_PARTNER_WEIGHT
                       + Decimal(associate) * BLENDED_ASSOCIATE_WEIGHT
                       + Decimal(paralegal) * BLENDED_PARALEGAL_WEIGHT)


def defense_invoice_audit(assignment, invoice):
    partner_hours = invoice["partner_hours"]
    associate_hours = invoice["associate_hours"]
    paralegal_hours = invoice["paralegal_hours"]
    block_hours = invoice["block_billed_hours"]
    expenses = invoice["expenses_cents"]

    partner_rate = Decimal(assignment["partner_rate_cents_per_hour"])
    associate_rate = Decimal(assignment["associate_rate_cents_per_hour"])
    paralegal_rate = Decimal(assignment["paralegal_rate_cents_per_hour"])

    # step 1
    billed_fees = round_cents(partner_hours * partner_rate
                              + associate_hours * associate_rate
                              + paralegal_hours * paralegal_rate)
    # step 2
    partner_excess_rate = partner_rate - Decimal(PARTNER_RATE_CAP_CENTS)
    if partner_excess_rate < ZERO:
        partner_excess_rate = ZERO
    associate_excess_rate = associate_rate - Decimal(ASSOCIATE_RATE_CAP_CENTS)
    if associate_excess_rate < ZERO:
        associate_excess_rate = ZERO
    rate_cap_excess = (round_cents(partner_hours * partner_excess_rate)
                       + round_cents(associate_hours * associate_excess_rate))
    post_rate_cap_fees = billed_fees - rate_cap_excess
    # step 3
    total_hours = partner_hours + associate_hours + paralegal_hours
    if total_hours == 0:
        block_share = ZERO
    else:
        block_share = Decimal(block_hours) / Decimal(total_hours)
    block_reduction = round_cents(Decimal(post_rate_cap_fees) * block_share
                                  * BLOCK_BILLING_REDUCTION_PCT)
    allowed_fees = post_rate_cap_fees - block_reduction
    # step 4
    expense_allowance = round_cents(Decimal(allowed_fees) * EXPENSE_CAP_PCT)
    expense_disallowance = expenses - expense_allowance
    if expense_disallowance < 0:
        expense_disallowance = 0
    # step 5
    allowed_amount = allowed_fees + (expenses - expense_disallowance)
    guideline_reduction = (rate_cap_excess + block_reduction
                          + expense_disallowance)
    disallowed_amount = billed_fees + expenses - allowed_amount
    return {
        "billed_fees_cents": billed_fees,
        "rate_cap_excess_cents": rate_cap_excess,
        "block_reduction_cents": block_reduction,
        "expense_disallowance_cents": expense_disallowance,
        "guideline_reduction_cents": guideline_reduction,
        "allowed_amount_cents": allowed_amount,
        "disallowed_amount_cents": disallowed_amount,
    }


def elapsed_days(from_dt, to_dt):
    seconds = (to_dt - from_dt).total_seconds()
    return int(seconds // 86400)


TIER_RANK = {"LOCAL": 0, "REGIONAL": 1, "NATIONAL": 2}
