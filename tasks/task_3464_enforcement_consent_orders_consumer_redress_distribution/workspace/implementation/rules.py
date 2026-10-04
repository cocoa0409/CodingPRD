"""Calculation rules (scaffold §1.3): complaint-velocity risk tier, civil penalty
accrual, the pinned 4-step redress waterfall, residual claim-rate rule, and the
timing constants. All money is integer cents; no floats anywhere.
"""
from timeutil import parse_iso, seconds

# --- complaint_velocity_risk_tier ---
ELEVATED_MIN = 10
CRITICAL_MIN = 50

# --- civil_penalty_accrual ---
RATE_STANDARD_PER_DAY_CENTS = 1000000
RATE_AGGRAVATED_PER_DAY_CENTS = 4353000
RATE_EGREGIOUS_PER_DAY_CENTS = 5000000
PROVISIONAL_PROJECTION_DAYS = 30

# --- redress_waterfall ---
LOSS_CAP_CENTS = 2500000
ADMIN_RESERVE_CAP_CENTS = 500000
FUND_OPEN_MINIMUM_CENTS = 1000000
# ADMIN_RESERVE_RATE = 0.10 exactly, applied as the rational 1/10.

# --- residual_disposition_rule ---
# CY_PRES_MIN_CLAIM_RATE = 0.60 exactly (3/5), >= semantics, rational comparison.

# --- check_lifecycle_timing ---
CHECK_STALE_DAYS = 90
CHECK_REISSUE_WINDOW_DAYS = 180
COMMENT_PERIOD_DAYS = 30
# SUSPENSION_MAX_ASSET_RATIO = 0.10 exactly (1/10).
FRAUD_WARNING_TEXT = (
    "WARNING: The FTC never requires payment or personal information to cash a "
    "refund check. Anyone who demands money or information in exchange for your "
    "refund is a scammer."
)

PENALTY_RATES = {
    "STANDARD": RATE_STANDARD_PER_DAY_CENTS,
    "AGGRAVATED": RATE_AGGRAVATED_PER_DAY_CENTS,
    "EGREGIOUS": RATE_EGREGIOUS_PER_DAY_CENTS,
}


def risk_tier(complaint_count_90d):
    """Boundary: exactly 10 is ELEVATED, exactly 50 is CRITICAL (>= semantics)."""
    if complaint_count_90d >= CRITICAL_MIN:
        return "CRITICAL"
    if complaint_count_90d >= ELEVATED_MIN:
        return "ELEVATED"
    return "STANDARD"


def provisional_penalty(severity, max_penalty_cents):
    days = PROVISIONAL_PROJECTION_DAYS
    amount = min(PENALTY_RATES[severity] * days, max_penalty_cents)
    return days, amount


def final_penalty(severity, detected_dt, cured_dt, max_penalty_cents):
    """final_days = max(1, floor((cured_on - detected_on) / 86400 seconds))."""
    delta = seconds(cured_dt) - seconds(detected_dt)
    days = int(delta.total_seconds()) // 86400
    days = max(1, days)
    amount = min(PENALTY_RATES[severity] * days, max_penalty_cents)
    return days, amount


def waterfall(approved_claims, total_collected_cents):
    """Pinned evaluation order (do not reorder):
    (1) eligible_i = min(documented_loss_cents_i, LOSS_CAP_CENTS); total_eligible = sum.
    (2) admin_reserve_cents = min(ceil(total_eligible / 10), ADMIN_RESERVE_CAP_CENTS).
    (3) distributable_pool_cents = total_collected_cents - admin_reserve_cents.
    (4) awards: full if pool covers; else per-claim floor FIRST, then the remainder
        one cent at a time in created_at-ascending order (earliest approved first).
    Returns (admin_reserve_cents, distributable_pool_cents, {claim_id: award}).
    """
    eligible = {
        c["id"]: min(c["documented_loss_cents"], LOSS_CAP_CENTS)
        for c in approved_claims
    }
    total_eligible = sum(eligible.values())
    reserve = min((total_eligible + 9) // 10, ADMIN_RESERVE_CAP_CENTS)
    pool = total_collected_cents - reserve
    if total_eligible == 0:
        return reserve, pool, {cid: 0 for cid in eligible}
    if pool >= total_eligible:
        return reserve, pool, dict(eligible)
    ordered = sorted(
        approved_claims, key=lambda c: (parse_iso(c["created_at"]), c["_seq"])
    )
    awards = {}
    distributed = 0
    for c in ordered:
        award = (pool * eligible[c["id"]]) // total_eligible
        awards[c["id"]] = award
        distributed += award
    remainder = pool - distributed
    while remainder > 0:
        for c in ordered:
            if remainder <= 0:
                break
            awards[c["id"]] += 1
            remainder -= 1
    return reserve, pool, awards


def cy_pres_eligible(approved_count, identified_count):
    """claim_rate >= 0.60 qualifies as CY_PRES; exactly 0.60 qualifies.
    Rational comparison: approved/identified >= 3/5  <=>  5*approved >= 3*identified."""
    if identified_count == 0:
        return False
    return approved_count * 5 >= identified_count * 3
