"""The twelve calculation rules of scaffold section 1.3.

Money is integer cents; every fractional cent is rounded half-up at the pinned
step before the next step consumes it (PRD 2.7).
"""

from decimal import Decimal, ROUND_HALF_UP

import clock

# --- constants ---------------------------------------------------------------
QUALITY_UPLIFT_RATE = Decimal("0.10")
SPONSOR_MONTHS_CAP = 120
SPONSOR_UPLIFT_DIVISOR = Decimal("10000.0")

BAND_FULL_DELIVERY = Decimal("0.99")
BAND_NEAR_FULL = Decimal("0.95")
BAND_PARTIAL = Decimal("0.90")
ADJUSTER_FULL_DELIVERY = Decimal("0.00")
ADJUSTER_NEAR_FULL = Decimal("0.05")
ADJUSTER_PARTIAL = Decimal("0.12")
ADJUSTER_SEVERE = Decimal("0.20")

COVERAGE_MIN_RATIO = Decimal("2.0")
EXPERIENCE_MONTHS_MIN = 120
PROJECTS_COMPLETED_MIN = 5
SUSPENSION_ESCALATION_COUNT = 2

FROZEN_DISTRESSED_COUNT = 2
FROZEN_FAILURE_COUNT = 2
WATCH_DISTRESSED_COUNT = 1

TIER_1_CEILING = 800000000
TIER_2_CEILING = 600000000
TIER_1_CAP = 300000000
TIER_2_CAP = 400000000

TIER_ORDER = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}

OCCUPANCY_WEIGHT = 35
DSCR_WEIGHT = 30
DSCR_CEILING = Decimal("1.5")
RESERVE_TARGET_CENTS = 50000000
RESERVE_POINTS = 20
TERM_POINTS = 15
SCORE_FLOOR = 0
SCORE_CEILING = 100

MONTHS_DIVISOR = 12
COVERAGE_MONTHS_MIN = 12

EQUITY_STEP_UP = Decimal("1.05")
SHORTFALL_SURCHARGE_PER_CALL = Decimal("0.01")

# Equity default band — a subscription defaults once its shortfall exceeds
# 20 percent of its commitment, rounded half-up (PRD 3.5).
DEFAULT_BAND_PCT = Decimal("0.20")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half-up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half-up to a whole number of cents, returned as an int."""
    return int(rhu(value, 0))


def rhu6(value):
    """Round half-up to six decimal places, returned as a float."""
    return float(rhu(value, 6))


# --- 1. underwriting_equity --------------------------------------------------
def preliminary_equity_cents(project):
    base = int(project["construction_budget_cents"]) - int(project["construction_loan_cents"])
    uplift = rhu_int(dec(base) * (dec(project["market_study_absorption_score"]) * QUALITY_UPLIFT_RATE))
    return base - uplift


def final_equity_cents(project, price_per_credit_dollar):
    credit_value = rhu_int(dec(project["total_credit_dollars_cents"]) * dec(price_per_credit_dollar))
    final_base = int(project["construction_budget_cents"]) - int(project["construction_loan_cents"])
    months = min(int(project["sponsor_experience_months"]), SPONSOR_MONTHS_CAP)
    sponsor_uplift = rhu_int(dec(final_base) * dec(months) / SPONSOR_UPLIFT_DIVISOR)
    return min(final_base, credit_value) - sponsor_uplift


def underwritten_equity_cents(project):
    if project.get("underwriting_stage") == "FINAL" and project.get("final_equity_cents") is not None:
        return int(project["final_equity_cents"])
    return int(project.get("preliminary_equity_cents") or 0)


# --- 2. capital_call_amount --------------------------------------------------
def delivery_ratio_of(committed_allocations):
    awarded = sum(int(a["awarded_credit_dollars_cents"]) for a in committed_allocations)
    delivered = sum(int(a["delivered_credit_dollars_cents"]) for a in committed_allocations)
    if awarded > 0:
        return dec(delivered) / dec(awarded)
    return Decimal("1.0")


def adjuster_band(delivery_ratio):
    """Half-open on the low side: an exact boundary takes the lower adjuster."""
    if delivery_ratio >= BAND_FULL_DELIVERY:
        return ADJUSTER_FULL_DELIVERY
    if delivery_ratio >= BAND_NEAR_FULL:
        return ADJUSTER_NEAR_FULL
    if delivery_ratio >= BAND_PARTIAL:
        return ADJUSTER_PARTIAL
    return ADJUSTER_SEVERE


def capital_call_amount(project, committed_allocations, milestone_share, current_adjuster):
    band = adjuster_band(delivery_ratio_of(committed_allocations))
    adjuster = max(band, dec(current_adjuster))
    base_call = rhu_int(dec(underwritten_equity_cents(project)) * dec(milestone_share))
    called = rhu_int(dec(base_call) * (Decimal(1) + adjuster))
    return float(adjuster), base_call, called


# --- 3. fund_pricing_yield ---------------------------------------------------
def fund_priced_fields(fund, allocations_rows):
    """`allocations_rows` are the COMMITTED/CLOSED allocations of non-EXITED projects."""
    price = dec(fund["price_per_credit_dollar"])
    awarded_total = sum(int(a["awarded_credit_dollars_cents"]) for a in allocations_rows)
    delivered_total = sum(int(a["delivered_credit_dollars_cents"]) for a in allocations_rows)
    priced_value = sum(rhu_int(dec(a["awarded_credit_dollars_cents"]) * price) for a in allocations_rows)
    realized_value = sum(rhu_int(dec(a["delivered_credit_dollars_cents"]) * price) for a in allocations_rows)
    return awarded_total, delivered_total, priced_value, realized_value


def priced_yield_pct(awarded_total, subscribed_equity_cents):
    if subscribed_equity_cents > 0:
        return rhu6((dec(awarded_total) - dec(subscribed_equity_cents)) / dec(subscribed_equity_cents))
    return 0.0


def realized_yield_pct(delivered_total, funded_equity_cents):
    if funded_equity_cents > 0:
        return rhu6((dec(delivered_total) - dec(funded_equity_cents)) / dec(funded_equity_cents))
    return 0.0


# --- 4. sponsor_eligibility --------------------------------------------------
def sponsor_eligibility(net_worth_cents, exposure_cents, months, completed,
                        escalated_count, distressed_count):
    coverage_ratio = dec(net_worth_cents) / dec(max(exposure_cents, 1))
    deeply_experienced = months >= EXPERIENCE_MONTHS_MIN and completed >= PROJECTS_COMPLETED_MIN
    eligible_by_coverage = coverage_ratio >= COVERAGE_MIN_RATIO or deeply_experienced
    if escalated_count >= SUSPENSION_ESCALATION_COUNT and distressed_count >= 1:
        return "SUSPENDED"
    if (not eligible_by_coverage) or distressed_count >= 1 or escalated_count >= 1:
        return "WATCH"
    return "ELIGIBLE"


# --- 5. fund_posture ---------------------------------------------------------
def fund_posture(project_rows):
    distressed = sum(1 for p in project_rows if p.get("status") == "DISTRESSED")
    failures = any(int(p.get("compliance_failure_count") or 0) >= FROZEN_FAILURE_COUNT
                   for p in project_rows)
    if distressed >= FROZEN_DISTRESSED_COUNT or failures:
        return "FROZEN"
    if distressed == WATCH_DISTRESSED_COUNT:
        return "WATCH"
    return "OPEN"


# --- 6. investor_allocation --------------------------------------------------
def tier_cap(risk_tier):
    if risk_tier == "TIER_1":
        return TIER_1_CAP
    if risk_tier == "TIER_2":
        return TIER_2_CAP
    return None  # TIER_3 is uncapped


def max_subscription_cents(fund, investor):
    remaining = int(fund["target_equity_cents"]) - int(fund["subscribed_equity_cents"])
    headroom = int(investor["committed_capacity_cents"]) - int(investor["outstanding_commitment_cents"])
    cap = tier_cap(investor["risk_tier"])
    if cap is not None:
        headroom = min(headroom, cap)
    return min(remaining, headroom)


# --- 7. credit_shortfall_waterfall -------------------------------------------
def credit_shortfall_waterfall(payable, ordered_subscriptions):
    """Pinned order: tier ASC, investor.created_at ASC, subscription.created_at ASC."""
    total_committed = sum(int(s["committed_cents"]) for s in ordered_subscriptions)
    shares = []
    for sub in ordered_subscriptions:
        if total_committed > 0:
            share = rhu_int(dec(payable) * dec(sub["committed_cents"]) / dec(total_committed))
        else:
            share = 0
        shares.append([sub, share])
    remainder = int(payable) - sum(s[1] for s in shares)
    index = 0
    while remainder > 0 and shares:
        shares[index % len(shares)][1] += 1
        remainder -= 1
        index += 1
    return shares


def waterfall_order(subscriptions_rows, investors_by_id):
    def key(sub):
        investor = investors_by_id.get(sub["investor_id"], {})
        return (TIER_ORDER.get(investor.get("risk_tier"), 9),
                investor.get("created_at") or "",
                sub.get("created_at") or "",
                sub.get("_seq", 0))
    return sorted(subscriptions_rows, key=key)


# --- 8. watch_list_risk_score ------------------------------------------------
def watch_list_risk_score(review, project):
    occupancy_points = rhu_int(OCCUPANCY_WEIGHT * dec(review["occupancy_pct"]))
    dscr_points = rhu_int(dec(DSCR_WEIGHT) * min(dec(review["dscr_observed"]), DSCR_CEILING) / DSCR_CEILING)
    reserve_points = RESERVE_POINTS if int(review["reserve_balance_cents"]) < RESERVE_TARGET_CENTS else 0
    violations = 0
    if clock.now() > clock._parse(project["placed_in_service_deadline"]):
        violations += 1
    if clock._parse(review["review_period_end"]) > clock.now():
        violations += 1
    term_points = TERM_POINTS * violations
    raw = occupancy_points + dscr_points + reserve_points + term_points
    return max(SCORE_FLOOR, min(SCORE_CEILING, raw))


# --- 9. operating_deficit_coverage -------------------------------------------
def operating_deficit_coverage(project, developer):
    deficit = max(0, int(project["debt_service_cents"]) - int(project["operating_pro_forma_noi_cents"]))
    monthly = rhu_int(dec(deficit) / dec(MONTHS_DIVISOR))
    annual = rhu_int(dec(deficit))
    months = int(developer["liquid_assets_cents"]) // max(monthly, 1)
    return monthly, annual, months, months >= COVERAGE_MONTHS_MIN


# --- 10. exit_option_price ---------------------------------------------------
def exit_option_price(project, paid_calls, shortfall_calls):
    cumulative = sum(int(c["settled_amount_cents"]) for c in paid_calls)
    step1 = rhu_int(dec(underwritten_equity_cents(project)) * EQUITY_STEP_UP)
    step2 = rhu_int(dec(step1) - dec(cumulative))
    step3 = rhu_int(dec(step2) * (Decimal(1) + SHORTFALL_SURCHARGE_PER_CALL * dec(len(shortfall_calls))))
    return max(0, step3), cumulative


# --- 12. portfolio_summary ---------------------------------------------------
def portfolio_summary(project_rows, allocations_rows, latest_review_by_project):
    project_count = len(project_rows)
    distressed_count = sum(1 for p in project_rows if p.get("status") == "DISTRESSED")
    total_awarded = sum(int(a["awarded_credit_dollars_cents"]) for a in allocations_rows)
    total_delivered = sum(int(a["delivered_credit_dollars_cents"]) for a in allocations_rows)
    total_committed_equity = sum(underwritten_equity_cents(p) for p in project_rows)
    score_sum = 0
    for project in project_rows:
        review = latest_review_by_project.get(project["id"])
        if review is not None:
            score_sum += int(review.get("risk_score") or 0)
    weighted = rhu_int(dec(score_sum) / dec(max(project_count, 1)))
    return {
        "project_count": project_count,
        "distressed_count": distressed_count,
        "total_awarded_credit_dollars_cents": total_awarded,
        "total_delivered_credit_dollars_cents": total_delivered,
        "total_committed_equity_cents": total_committed_equity,
        "weighted_average_risk_score": weighted,
    }
