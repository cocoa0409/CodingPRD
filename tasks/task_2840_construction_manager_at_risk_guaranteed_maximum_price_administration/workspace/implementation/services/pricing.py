"""Money build-ups (PRD 3.2 and 3.9)."""
from decimal import Decimal

from money import MONEY_ZERO, q2, q4

CM_SHARE_CAP_OF_FEE_PCT = Decimal("0.25")
SAVINGS_TIER_LOW = Decimal("0.02")
SAVINGS_TIER_MID = Decimal("0.05")
SAVINGS_RATE_LOW = Decimal("0.25")
SAVINGS_RATE_MID = Decimal("0.35")
SAVINGS_RATE_HIGH = Decimal("0.50")


def gmp_buildup(cm_fee_pct, insurance_rate, cost_of_work_total,
                general_conditions_total, owner_contingency_amount,
                construction_contingency_amount):
    """Four ordered steps; steps 1-3 each round half up to two places."""
    base = cost_of_work_total + general_conditions_total
    provisional_fee_amount = q2(cm_fee_pct * base)
    insurance_amount = q2(insurance_rate * (base + provisional_fee_amount))
    cm_fee_amount = q2(cm_fee_pct * (base + insurance_amount))
    gmp_amount = q2(
        base
        + insurance_amount
        + cm_fee_amount
        + owner_contingency_amount
        + construction_contingency_amount
    )
    return {
        "provisional_fee_amount": provisional_fee_amount,
        "insurance_amount": insurance_amount,
        "cm_fee_amount": cm_fee_amount,
        "gmp_amount": gmp_amount,
    }


def cm_share_rate(savings_pct):
    if savings_pct <= SAVINGS_TIER_LOW:
        return SAVINGS_RATE_LOW
    if savings_pct <= SAVINGS_TIER_MID:
        return SAVINGS_RATE_MID
    return SAVINGS_RATE_HIGH


def shared_savings(gmp_amount, cm_fee_amount, insurance_amount, settled_cost):
    """Five ordered steps; a non-positive pool zeroes all three figures."""
    recoverable_base = q2(gmp_amount - cm_fee_amount - insurance_amount)
    savings_pool = q2(recoverable_base - settled_cost)
    if savings_pool <= MONEY_ZERO:
        return {
            "savings_pool": MONEY_ZERO,
            "cm_share": MONEY_ZERO,
            "owner_share": MONEY_ZERO,
        }
    savings_pct = q4(savings_pool / gmp_amount)
    rate = cm_share_rate(savings_pct)
    uncapped_cm_share = q2(rate * savings_pool)
    cm_share_cap = q2(CM_SHARE_CAP_OF_FEE_PCT * cm_fee_amount)
    cm_share = uncapped_cm_share if uncapped_cm_share < cm_share_cap else cm_share_cap
    owner_share = q2(savings_pool - cm_share)
    return {
        "savings_pool": savings_pool,
        "cm_share": cm_share,
        "owner_share": owner_share,
    }
