"""Calculation services (scaffold §calculations, PRD §2.5 / §3)."""

from decimal import Decimal, ROUND_HALF_UP

COMPONENT_CREDITS = {
    "1040_SIMPLE": 7500,
    "1040_ITEMIZED": 15000,
    "1040_BUSINESS": 30000,
    "1040_MULTI_STATE": 20000,
    "AMENDED_RETURN": 12000,
    "PRIOR_YEAR_REVIEW": 8000,
}

TIER_MULTIPLIER = {
    "ASSOCIATE": Decimal("1.0"),
    "SENIOR": Decimal("1.25"),
    "MASTER": Decimal("1.5"),
    "ENROLLED_AGENT": Decimal("1.75"),
}

# Tier order for upgrade (strictly higher multiplier)
TIER_ORDER = ["ASSOCIATE", "SENIOR", "MASTER", "ENROLLED_AGENT"]

BASE_PREMIUM = {
    "STANDARD": 4900,
    "PLUS": 9900,
}
SIMPLE_CAP = 15000
STANDARD_CAP = 30000

DAILY_RATE = Decimal("0.000273972602739726")

ACCRUAL_MARKUP = Decimal("1.1")

DEFECT_WEIGHT = Decimal("400")
CLAIM_WEIGHT = Decimal("300")
OK_THRESHOLD = 80
WATCH_THRESHOLD = 60


def _round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_half_up_to_100(value):
    """Round a Decimal (cents) to the nearest 100 cents, half-up."""
    hundreds = (value / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(hundreds) * 100


def sum_credits(components):
    return sum(COMPONENT_CREDITS[c] for c in components)


def prep_fee_quote(components, tier):
    """sum credits, multiply total by tier multiplier, round once to nearest 100 cents."""
    credits = sum_credits(components)
    raw = Decimal(credits) * TIER_MULTIPLIER[tier]
    return _round_half_up_to_100(raw)


def protection_premium(components, tier):
    credits = sum_credits(components)
    base = Decimal(BASE_PREMIUM[tier])
    if credits <= SIMPLE_CAP:
        premium = base
    elif credits <= STANDARD_CAP:
        premium = base * Decimal("1.5")
    else:
        premium = base * Decimal("2.0")
    return _round_half_up_cents(premium)


def interest_accrual(tax_delta_cents, due_at, paid_at):
    """days between due_at (exclusive) and paid_at (inclusive); 0 when paid_at <= due_at."""
    delta = paid_at - due_at
    days = delta.days
    if days <= 0:
        return 0
    product = Decimal(tax_delta_cents) * DAILY_RATE * Decimal(days)
    return _round_half_up_cents(product)


def reimbursement_payout(claim, notice, product):
    """Compute the three payout components for a claim.

    Returns (base, interest, penalty, total).
    """
    if claim["error_attribution"] == "PREPARER_ERROR":
        base = notice["tax_delta_cents"]
        interest = notice["interest_cents"] or 0
        penalty = notice["penalty_cents"] if (product and product["tier"] == "PLUS") else 0
    else:  # CLIENT_DATA_ERROR
        base = 0
        interest = notice["interest_cents"] or 0
        penalty = 0
    total = base + interest + penalty
    return base, interest, penalty, total


def final_liability(payout_total, payout_base):
    """Liability fold: total + base (base counted twice)."""
    return payout_total + payout_base


def accrual_contribution(payout_total):
    """Per-claim accrual: round_half_up(payout_total * 1.1)."""
    return _round_half_up_cents(Decimal(payout_total) * ACCRUAL_MARKUP)


def office_quality_score(defects, examined, resolved_claims_in_period):
    """quality_score = round_half_up(100 - 400*defect_rate - 300*claim_rate), clamp [0,100]."""
    defect_rate = Decimal(defects) / Decimal(examined)
    claim_rate = Decimal(resolved_claims_in_period) / Decimal(examined)
    raw = Decimal(100) - DEFECT_WEIGHT * defect_rate - CLAIM_WEIGHT * claim_rate
    score = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score


def posture_for_score(score):
    if score >= OK_THRESHOLD:
        return "OK"
    if score >= WATCH_THRESHOLD:
        return "WATCH"
    return "PROBATION"
