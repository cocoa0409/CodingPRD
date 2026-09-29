"""Business calculations: valuation, pricing, the insurance requirement matrix,
interest accrual, the payment waterfall, settlement and borrower exposure."""

from fractions import Fraction

import constants as K
import core
import store
from core import round_half_up


# --------------------------------------------------------------------------
# calculations.unit_book_valuation
# --------------------------------------------------------------------------

def location_key_for(unit):
    """Step 3 — the cross-aggregate read from unit into its community."""
    if unit["placement_type"] == "PRIVATE_LAND":
        return "PRIVATE_LAND"
    community = store.communities.get(unit.get("community_id"))
    if community is not None and community["operator_agreement_status"] == "EXECUTED":
        return "COMMUNITY_WITH_AGREEMENT"
    return "COMMUNITY_WITHOUT_AGREEMENT"


def compute_valuation(unit, guide, variant):
    valuation_year = core.now().year
    age_years = max(0, valuation_year - unit["model_year"])
    depreciation_bps = min(age_years * guide["annual_depreciation_bps"],
                           10000 - K.DEPRECIATION_FLOOR_BPS)

    if unit["width_class"] == "MULTI_WIDE":
        width_multiplier_bps = guide["multi_wide_multiplier_bps"]
    else:
        width_multiplier_bps = guide["single_wide_multiplier_bps"]

    book_base_cents = round_half_up(Fraction(
        unit["square_feet"] * guide["base_value_per_sqft_cents"]
        * width_multiplier_bps * (10000 - depreciation_bps),
        10000 * 10000))

    location_key = location_key_for(unit)

    condition_adjustment_cents = round_half_up(Fraction(
        book_base_cents * K.CONDITION_ADJUSTMENT_BPS[unit["condition_grade"]], 10000))
    location_adjustment_cents = round_half_up(Fraction(
        book_base_cents * K.LOCATION_ADJUSTMENT_BPS[location_key], 10000))
    if variant == "ORIGINATION":
        installation_adjustment_cents = K.INSTALLATION_ADJUSTMENT_CENTS[unit["installation_type"]]
    else:
        installation_adjustment_cents = 0

    adjusted_cents = (book_base_cents + condition_adjustment_cents
                      + location_adjustment_cents + installation_adjustment_cents)

    if variant == "ORIGINATION":
        forced_sale_discount_cents = 0
        detach_and_move_cost_cents = 0
        certified_value_cents = adjusted_cents
    else:
        forced_sale_discount_cents = round_half_up(Fraction(
            adjusted_cents * K.RECOVERY_FORCED_SALE_DISCOUNT_BPS, 10000))
        if location_key == "COMMUNITY_WITHOUT_AGREEMENT":
            detach_and_move_cost_cents = K.DETACH_AND_MOVE_COST_CENTS
        else:
            detach_and_move_cost_cents = 0
        certified_value_cents = max(0, adjusted_cents - forced_sale_discount_cents
                                    - detach_and_move_cost_cents)

    return {
        "valuation_year": valuation_year,
        "location_key": location_key,
        "book_base_cents": book_base_cents,
        "condition_adjustment_cents": condition_adjustment_cents,
        "location_adjustment_cents": location_adjustment_cents,
        "installation_adjustment_cents": installation_adjustment_cents,
        "forced_sale_discount_cents": forced_sale_discount_cents,
        "detach_and_move_cost_cents": detach_and_move_cost_cents,
        "certified_value_cents": certified_value_cents,
    }


# --------------------------------------------------------------------------
# calculations.loan_rate_and_term
# --------------------------------------------------------------------------

def credit_tier_bps(score):
    if score >= 780:
        return -200
    if score >= 720:
        return -125
    if score >= 660:
        return 0
    if score >= 600:
        return 200
    return 425


def ltv_tier_bps(ltv_bps):
    if ltv_bps <= 8000:
        return 0
    if ltv_bps <= 9000:
        return 75
    return 150


def compute_ltv_bps(principal_cents, certified_value_cents):
    """None signals a value the cap can never accommodate (zero collateral value)."""
    if certified_value_cents <= 0:
        return None
    return round_half_up(Fraction(principal_cents * 10000, certified_value_cents))


def compute_apr_bps(loan, borrower, unit, ltv_bps):
    raw = (K.BASE_APR_BPS
           + K.PLACEMENT_SPREAD_BPS[loan["placement_type"]]
           + K.CLASSIFICATION_SPREAD_BPS[loan["collateral_classification"]]
           + credit_tier_bps(borrower["credit_score"])
           + ltv_tier_bps(ltv_bps))
    if unit["wind_zone"] == 3 and unit["installation_type"] == "PIER_AND_ANCHOR":
        raw += K.WIND_EXPOSURE_SURCHARGE_BPS
    return min(K.APR_CEILING_BPS, max(K.APR_FLOOR_BPS, raw))


def compute_term_months(loan, unit, valuation):
    remaining_life_months = max(0, (K.USEFUL_LIFE_YEARS
                                    - (valuation["valuation_year"] - unit["model_year"])) * 12)
    return min(loan["requested_term_months"],
               K.MAX_TERM_BY_PLACEMENT[loan["placement_type"]],
               K.MAX_TERM_BY_CLASSIFICATION[loan["collateral_classification"]],
               remaining_life_months)


# --------------------------------------------------------------------------
# calculations.force_placed_premium — the requirement matrix
# --------------------------------------------------------------------------

def insurable_value_cents(loan):
    valuation = store.valuations.get(loan.get("origination_valuation_id"))
    if valuation is None:
        return 0
    return valuation["certified_value_cents"]


def exposure_cents(loan):
    if loan["underwriting_state"] == "FUNDED":
        return loan["principal_balance_cents"]
    return loan["principal_cents"]


def required_coverage_cents(loan):
    ratio = K.REQUIRED_COVERAGE_BPS[loan["collateral_classification"]]
    return max(exposure_cents(loan),
               round_half_up(Fraction(insurable_value_cents(loan) * ratio, 10000)))


def wind_required(unit):
    if unit["wind_zone"] == 3:
        return True
    return unit["wind_zone"] == 2 and unit["installation_type"] == "PIER_AND_ANCHOR"


def score_compliance(required_cents, wind_needed, has_endorsement, dwelling_cents):
    """Wind is graded first: a policy failing both reports DEFICIENT_WIND."""
    if wind_needed and not has_endorsement:
        return "DEFICIENT_WIND"
    if dwelling_cents < required_cents:
        return "DEFICIENT_COVERAGE"
    return "COMPLIANT"


def rescore_policy(policy, loan, unit):
    """Re-score one policy against the loan's current requirement matrix.

    Returns True when a stored field actually moved.
    """
    required = required_coverage_cents(loan)
    state = score_compliance(required, wind_required(unit),
                             policy["wind_endorsement"], policy["dwelling_coverage_cents"])
    changed = False
    if policy["required_coverage_cents"] != required:
        policy["required_coverage_cents"] = required
        changed = True
    if policy["compliance_state"] != state:
        policy["compliance_state"] = state
        changed = True
    if changed:
        store.touch(policy)
    return changed


def rescore_active_policies(loan, unit):
    changed = False
    for policy in store.policies_of_loan(loan["id"]):
        if policy["status"] == "ACTIVE":
            if rescore_policy(policy, loan, unit):
                changed = True
    return changed


def recompute_insurance_compliance(loan):
    """PRD 2.10: recomputed from whichever policy remains ACTIVE."""
    rows = store.policies_of_loan(loan["id"])
    if not rows:
        return False
    actives = [p for p in rows if p["status"] == "ACTIVE"]
    value = "NON_COMPLIANT"
    for policy in actives:
        if policy["compliance_state"] == "COMPLIANT":
            value = "COMPLIANT"
            break
    if loan["insurance_compliance"] != value:
        loan["insurance_compliance"] = value
        return True
    return False


def force_placed_premium_cents(required_cents, wind_zone, coverage_days):
    """Two pinned rounding points, in this order."""
    rate_bps = K.FORCE_PLACED_BASE_RATE_BPS + K.FORCE_PLACED_WIND_SURCHARGE_BPS[wind_zone]
    annual_premium_cents = round_half_up(Fraction(required_cents * rate_bps, 10000))
    return annual_premium_cents, round_half_up(Fraction(annual_premium_cents * coverage_days, 365))


def unearned_premium_refund_cents(policy):
    remaining_days = core.calendar_days(core.now(), policy["expiry_date"])
    coverage_days = policy["coverage_days"]
    if coverage_days <= 0:
        return 0
    return round_half_up(Fraction(policy["premium_cents"] * remaining_days, coverage_days))


# --------------------------------------------------------------------------
# calculations.interest_accrual and payment_waterfall_allocation
# --------------------------------------------------------------------------

def accrual_preview(loan):
    """Accrue exactly once per servicing operation: one multiply, one rounding."""
    days = core.calendar_days(loan["last_accrual_date"], core.now())
    if days < 0:
        days = 0
    apr_bps = loan["apr_bps"] or 0
    accrued = round_half_up(Fraction(loan["principal_balance_cents"] * apr_bps * days,
                                     10000 * 365))
    return days, accrued


def commit_accrual(loan, accrued):
    loan["interest_accrued_unpaid_cents"] += accrued
    loan["last_accrual_date"] = core.now()


def allocation_variant_for(loan):
    if loan["collateral_classification"] == "PERSONAL_PROPERTY":
        return "CHATTEL_CONTRACT_ORDER"
    return "REAL_PROPERTY_ESCROW_FIRST"


def waterfall_order(variant):
    if variant == "CHATTEL_CONTRACT_ORDER":
        return K.CHATTEL_CONTRACT_ORDER
    return K.REAL_PROPERTY_ESCROW_FIRST


def allocate(loan, amount_cents, interest_outstanding):
    """Strictly sequential fill; no rounding occurs inside the waterfall."""
    buckets = {
        "interest": interest_outstanding,
        "fees": loan["fees_outstanding_cents"],
        "force_placed": loan["force_placed_premium_outstanding_cents"],
        "escrow": max(0, loan["escrow_target_cents"] - loan["escrow_balance_cents"]),
        "principal": loan["principal_balance_cents"],
    }
    variant = allocation_variant_for(loan)
    remaining = amount_cents
    applied = {}
    for bucket in waterfall_order(variant):
        take = min(remaining, buckets[bucket])
        applied[bucket] = take
        remaining -= take
    return variant, applied, remaining


def apply_allocation(loan, applied):
    loan["interest_accrued_unpaid_cents"] -= applied["interest"]
    loan["fees_outstanding_cents"] -= applied["fees"]
    loan["force_placed_premium_outstanding_cents"] -= applied["force_placed"]
    loan["escrow_balance_cents"] += applied["escrow"]
    loan["principal_balance_cents"] -= applied["principal"]


def payoff_amount_cents(loan):
    return (loan["interest_accrued_unpaid_cents"]
            + loan["fees_outstanding_cents"]
            + loan["force_placed_premium_outstanding_cents"]
            + loan["principal_balance_cents"]
            - loan["escrow_balance_cents"])


# --------------------------------------------------------------------------
# calculations.delinquency_and_default_eligibility
# --------------------------------------------------------------------------

def delinquent_days_for(loan):
    return max(0, core.calendar_days(loan["next_due_date"], core.now()))


def default_threshold_days(loan):
    threshold = K.DEFAULT_ELIGIBLE_DAYS[loan["collateral_classification"]]
    if (loan["placement_type"] == "COMMUNITY"
            and loan["lot_rent_months_delinquent"] >= K.LOT_RENT_ACCELERATION_MONTHS):
        threshold = max(K.DELINQUENCY_THRESHOLD_DAYS,
                        threshold - K.LOT_RENT_ACCELERATION_DAYS)
    return threshold


# --------------------------------------------------------------------------
# calculations.deficiency_settlement
# --------------------------------------------------------------------------

def commission_tier_bps(gross_proceeds_cents):
    for ceiling, bps in K.COMMISSION_TIER_BPS:
        if gross_proceeds_cents <= ceiling:
            return bps
    return K.COMMISSION_TOP_TIER_BPS


def commission_bps_for(gross_proceeds_cents, unit):
    bps = commission_tier_bps(gross_proceeds_cents)
    if unit["placement_type"] == "COMMUNITY":
        community = store.communities.get(unit.get("community_id"))
        if community is not None and community["operator_agreement_status"] == "EXECUTED":
            bps += community["sales_commission_bps"]
    return bps


def capitalized_refurbishment_cents(case):
    total = 0
    for line in case["refurbishment_line_items"]:
        if line["cost_class"] == "CAPITALIZED":
            total += line["cost_cents"]
    return total


def settle(case, loan, unit):
    gross = case["resale_price_cents"]
    bps = commission_bps_for(gross, unit)
    commission = round_half_up(Fraction(gross * bps, 10000))
    refurbishment = capitalized_refurbishment_cents(case)
    net = gross - commission - refurbishment
    payoff = (loan["principal_balance_cents"]
              + loan["interest_accrued_unpaid_cents"]
              + loan["fees_outstanding_cents"]
              + loan["force_placed_premium_outstanding_cents"]
              + case["recovery_expense_cents"]
              - loan["escrow_balance_cents"])
    deficiency = max(0, payoff - net)
    surplus = max(0, net - payoff)
    return {
        "gross_proceeds_cents": gross,
        "commission_bps": bps,
        "commission_cents": commission,
        "refurbishment_cost_cents": refurbishment,
        "net_proceeds_cents": net,
        "payoff_amount_cents": payoff,
        "deficiency_balance_cents": deficiency,
        "surplus_cents": surplus,
    }


# --------------------------------------------------------------------------
# calculations.borrower_exposure
# --------------------------------------------------------------------------

EXPOSURE_SERVICING_STATES = ("CURRENT", "DELINQUENT", "DEFAULT", "RECOVERY")


def recompute_borrower_exposure(borrower):
    if borrower is None:
        return False
    total = 0
    held_units = set()
    for loan in store.loans.values():
        if loan["borrower_id"] != borrower["id"]:
            continue
        if loan["servicing_state"] in EXPOSURE_SERVICING_STATES:
            total += loan["principal_balance_cents"]
        unit = store.units.get(loan["unit_id"])
        if unit is not None and unit["recovery_hold"]:
            held_units.add(unit["id"])
    count = len(held_units)
    status = "SUSPENDED" if count > 0 else "ACTIVE"
    changed = False
    if borrower["total_outstanding_principal_cents"] != total:
        borrower["total_outstanding_principal_cents"] = total
        changed = True
    if borrower["units_under_recovery_hold_count"] != count:
        borrower["units_under_recovery_hold_count"] = count
        changed = True
    if borrower["status"] != status:
        borrower["status"] = status
        changed = True
    if changed:
        store.touch(borrower)
    return changed


def recompute_exposure_for_loan(loan):
    return recompute_borrower_exposure(store.borrowers.get(loan["borrower_id"]))
