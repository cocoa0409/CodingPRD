"""Every calculation of PRD 3, with the rounding taken at the named steps only.

PRD 2.6: money is whole cents, rates are basis points over 10,000, rounding is
ROUND_HALF_UP and is applied per step (round-then-chain), never once at the end.
Durations use a ceiling and score conversions use a floor; both are called out
where they occur and neither is a half-up rounding.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import clock

BPS_WHOLE = 10000

MAX_NEGOTIATION_ROUNDS = 4
FILE_REJECT_THRESHOLD_BPS = 500
VERIFICATION_TTL_HOURS = 72
DISPUTE_RESPONSE_HOURS = 120
DISPUTE_FILING_DAYS = 30
MAX_INFO_REQUESTS = 2
FRAUD_BLOCK_THRESHOLD = 70
MERCHANT_SUSPEND_SCORE = 40
INTEGRATION_STALE_DAYS = 45
MAX_CONCURRENT_FEATURED_PER_CATEGORY = 2
MERCHANT_SLOT_COOLDOWN_DAYS = 7
PARTNER_MIN_EMPLOYER_COHORT = 2
DEFAULT_PRIVACY_MIN_COHORT_SIZE = 8


def half_up(numerator, denominator=1):
    """Round a rational to a whole number, half away from zero."""
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def half_up_decimal(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, rate_bps):
    """amount * rate / 10,000, rounded half up to whole cents."""
    return half_up(int(amount_cents) * int(rate_bps), BPS_WHOLE)


def ceil_days(start, end):
    """Duration in whole days, rounded UP (PRD 2.6 calls out the ceiling)."""
    seconds = (end - start).total_seconds()
    return int(math.ceil(seconds / 86400.0))


def floor_days(start, end):
    seconds = (end - start).total_seconds()
    return int(seconds // 86400)


# ---------------------------------------------------------------------------
# PRD 3.3 -- eligibility batch invalid-record ratio
# ---------------------------------------------------------------------------

def invalid_ratio_bps(invalid_record_count, record_count):
    if not record_count:
        return 0
    return half_up(int(invalid_record_count) * BPS_WHOLE, int(record_count))


def batch_rejects(invalid_record_count, record_count):
    """The 500 bps boundary is inclusive: exactly 500 validates."""
    return invalid_ratio_bps(invalid_record_count, record_count) > FILE_REJECT_THRESHOLD_BPS


# ---------------------------------------------------------------------------
# PRD 3.6 -- placement slot pricing, five ordered steps
# ---------------------------------------------------------------------------

def reach_surcharge_bps(eligible_headcount):
    if eligible_headcount <= 3:
        return 0
    if eligible_headcount <= 20:
        return 1500
    return 3000


def volume_discount_bps(gross_fee_cents):
    """The tier keys on the post-surcharge gross, never on the bare base."""
    if gross_fee_cents < 100000:
        return 0
    if gross_fee_cents < 200000:
        return 500
    return 1200


def price_slot(placement_fee_base_cents, slot_window_start, slot_window_end,
               eligible_headcount):
    duration = ceil_days(slot_window_start, slot_window_end)
    if duration < 1:
        duration = 1
    base = int(placement_fee_base_cents) * duration
    surcharge_bps = reach_surcharge_bps(eligible_headcount)
    surcharge = apply_bps(base, surcharge_bps)
    gross = base + surcharge
    discount_bps = volume_discount_bps(gross)
    discount = apply_bps(gross, discount_bps)
    return {
        "slot_duration_days": duration,
        "base_fee_cents": base,
        "reach_surcharge_bps": surcharge_bps,
        "reach_surcharge_cents": surcharge,
        "gross_fee_cents": gross,
        "volume_discount_bps": discount_bps,
        "volume_discount_cents": discount,
        "placement_fee_cents": gross - discount,
    }


# ---------------------------------------------------------------------------
# PRD 3.7 -- redemption line economics, five ordered steps
# ---------------------------------------------------------------------------

def line_economics(gross_amount_cents, discount_type, discount_value_bps,
                   discount_value_cents, commission_rate_bps,
                   employer_revenue_share_bps, revenue_share_enabled):
    gross = int(gross_amount_cents)
    if discount_type == "PERCENT":
        discount = min(gross, apply_bps(gross, int(discount_value_bps or 0)))
    else:
        discount = min(int(discount_value_cents or 0), gross)
    net = gross - discount
    commission = apply_bps(net, int(commission_rate_bps or 0))
    if revenue_share_enabled:
        # A slice of the ALREADY-ROUNDED commission, never of net_charged.
        share = apply_bps(commission, int(employer_revenue_share_bps or 0))
    else:
        share = 0
    return {
        "discount_amount_cents": discount,
        "net_charged_cents": net,
        "commission_amount_cents": commission,
        "employer_share_cents": share,
        "provider_net_cents": commission - share,
    }


# ---------------------------------------------------------------------------
# PRD 3.7 -- fraud risk, one formula in two variants
# ---------------------------------------------------------------------------

def fraud_score(variant, membership, prior_redemptions, gross_amount_cents=None,
                merchant_failure_score=0):
    """prior_redemptions is already the same membership's OTHER redemptions."""
    now = clock.now()
    if variant == "SCREENING":
        lookback_hours = 24
        statuses = ("PENDING",)
    else:
        lookback_hours = 168
        statuses = ("PENDING", "VERIFIED", "FAILED")

    points = 0
    if membership.get("employment_status") == "LEAVE":
        points += 15

    floor_instant = clock.plus_hours(now, -lookback_hours)
    prior = 0
    for row in prior_redemptions:
        if row.get("verification_status") not in statuses:
            continue
        created = row["created_at"]
        if created >= floor_instant and created < now:
            prior += 1
    points += min(40, 8 * prior)

    valid_from = membership.get("eligibility_valid_from")
    if valid_from is not None and now < clock.plus_days(valid_from, 7):
        points += 10

    if variant == "AUDIT":
        amount_points = int(int(gross_amount_cents or 0) // 10000)
        points += min(25, amount_points)
        if int(merchant_failure_score or 0) >= 20:
            points += 10

    return min(100, points)


# ---------------------------------------------------------------------------
# PRD 3.8 -- decaying fulfilment failure score
# ---------------------------------------------------------------------------

def decay_factor(age_days):
    if age_days <= 30:
        return Decimal("1.0")
    if age_days <= 90:
        return Decimal("0.5")
    return Decimal("0")


def fulfillment_failure_score(fault_disputes):
    """20 points per merchant-fault dispute, decayed, summed, rounded at the end."""
    total = Decimal(0)
    now = clock.now()
    for dispute in fault_disputes:
        resolved_at = dispute.get("resolved_at")
        if resolved_at is None:
            continue
        age = floor_days(resolved_at, now)
        total += Decimal(20) * decay_factor(age)
    return half_up_decimal(total)
