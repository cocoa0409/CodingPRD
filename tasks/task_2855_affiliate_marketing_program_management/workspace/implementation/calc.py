"""All seven calculations, transcribed from PRD sections 3.2-3.9 and the
scaffold calculation blocks.  Money is integer cents, rates integer basis
points, and every rounding step is half up.
"""

from decimal import Decimal

from common import D, clamp, rhu1, rhu_int

# --- site_quality_composite_score -----------------------------------------

SOURCE_MULTIPLIER = {
    "ORGANIC_SEARCH": Decimal("1.00"),
    "CONTENT_NEWSLETTER": Decimal("0.95"),
    "SOCIAL_ORGANIC": Decimal("0.90"),
    "PAID_SEARCH": Decimal("0.75"),
    "COUPON_DIRECTORY": Decimal("0.65"),
    "CASHBACK_PORTAL": Decimal("0.60"),
    "INCENTIVIZED_TRAFFIC": Decimal("0.40"),
}
PENALTY_PER_FLAG = Decimal("10")
PENALTY_CAP = Decimal("30")
RESTRICTED_PENALTY_CAP = Decimal("45")
RESTRICTED_METHOD_MULTIPLIER = Decimal("0.90")
RESTRICTED_METHODS = ("TRADEMARK_PAID_SEARCH", "COUPON_FEED")

# --- gate thresholds -------------------------------------------------------

SQ_PASS_FLOOR = Decimal("60.0")
SQ_CONDITIONAL_FLOOR = Decimal("45.0")
BRAND_SUITABILITY_FLOOR = Decimal("70.0")

# --- attribution -----------------------------------------------------------

FULL_CREDIT_SHARE_BPS = 10000
INCREMENTALITY_CREDIT_SHARE_BPS = 3000

# --- incrementality --------------------------------------------------------

PARTNER_TYPE_DISCOUNT_BPS = {
    "CONTENT": 0,
    "INFLUENCER": 0,
    "PAID_SEARCH": 500,
    "SUB_NETWORK": 500,
    "COUPON": 1500,
    "LOYALTY_CASHBACK": 2000,
}
TIER_LOW_CEILING_BPS = 3500
TIER_MEDIUM_CEILING_BPS = 6000

# --- fraud -----------------------------------------------------------------

SEVERITY_WEIGHT = {
    "COOKIE_STUFFING": 40,
    "FORCED_CLICK": 30,
    "UNAUTHORIZED_COUPON": 25,
    "TRADEMARK_BIDDING": 20,
}
# PRD 3.7 moves `open_violation_case_count` in exactly two places: it "rises by
# the number of cases opened", and a verification "whose outcome is cleared ...
# lowers the partner's `open_violation_case_count` by one".  No other branch --
# including the upheld verification that ends a case at `UPHELD` -- lowers it,
# so an `UPHELD` case still counts, exactly as it still counts at full weight in
# the point-in-time figure.  Only `VERIFIED_CLEARED` leaves the set.
OPEN_CASE_STATES = ("OPEN", "REMEDIATION_REQUESTED", "REMEDIATION_SUBMITTED",
                    "ESCALATED", "UPHELD")
POINT_IN_TIME_STATES = ("OPEN", "REMEDIATION_REQUESTED",
                        "REMEDIATION_SUBMITTED", "ESCALATED", "UPHELD")
TRAILING_WINDOW_DAYS = 90
FRAUD_SUSPENSION_THRESHOLD = 70
REINSTATEMENT_TRAILING_CEILING = Decimal("25.0")
FORCED_CLICK_RATIO_THRESHOLD_BPS = 1500
COOKIE_STUFFING_INDEX_THRESHOLD = 60
CASE_ESCALATION_FAILED_VERIFICATIONS = 2

# --- settlement ------------------------------------------------------------

MIN_PAYOUT_CENTS = 2500
VALIDATION_HOLD_DAYS = 30
DEFAULT_BACKUP_WITHHOLDING_BPS = 2400
APPROVAL_LIMIT_CENTS = 5000000
VARIANCE_TOLERANCE_BPS = 50
MAX_SUB_AFFILIATE_DEPTH = 1
MAX_REVISION_ROUNDS = 2
SCAN_COOLDOWN_HOURS = 24


def site_quality_score(domain_authority, content_originality_pct,
                       broken_link_ratio_bps, brand_safety_flag_count,
                       primary_traffic_source, declared_promo_methods):
    """base = 0.45*DA + 0.35*CO + 0.20*max(0, 100 - BLR/100), scaled by the
    traffic-source multiplier, scaled again by 0.90 when a restricted promo
    method is declared, then reduced by the flag penalty.  Rounded exactly
    once, at the very end."""
    link_component = D(100) - (D(broken_link_ratio_bps) / D(100))
    if link_component < 0:
        link_component = D(0)
    base = (D("0.45") * D(domain_authority)
            + D("0.35") * D(content_originality_pct)
            + D("0.20") * link_component)
    multiplier = SOURCE_MULTIPLIER[primary_traffic_source]
    restricted = any(m in RESTRICTED_METHODS for m in (declared_promo_methods or []))
    scaled = base * multiplier
    if restricted:
        scaled = scaled * RESTRICTED_METHOD_MULTIPLIER
    cap = RESTRICTED_PENALTY_CAP if restricted else PENALTY_CAP
    penalty = PENALTY_PER_FLAG * D(brand_safety_flag_count)
    if penalty > cap:
        penalty = cap
    return rhu1(clamp(scaled - penalty, D(0), D(100)))


def brand_suitability_score(restricted_vertical_overlap_bps,
                            brand_safety_flag_count):
    raw = (D(100) - (D(restricted_vertical_overlap_bps) / D(100))
           - D(12) * D(brand_safety_flag_count))
    return rhu1(clamp(raw, D(0), D(100)))


def screening_outcome(site_quality, brand_suitability):
    sq = D(str(site_quality))
    bs = D(str(brand_suitability))
    if bs < BRAND_SUITABILITY_FLOOR or sq < SQ_CONDITIONAL_FLOOR:
        return "FAIL"
    if sq >= SQ_PASS_FLOOR:
        return "PASS"
    return "CONDITIONAL"


def gross_commission_cents(order_total_cents, rate_bps):
    return rhu_int(D(order_total_cents) * D(rate_bps) / D(10000))


def payable_commission_cents(gross_cents, credit_share_bps):
    """Applied to the already-rounded gross; computing this in one expression
    from the order total is forbidden."""
    return rhu_int(D(gross_cents) * D(credit_share_bps) / D(10000))


def incrementality(partner_type, attributed_conversion_count,
                   new_customer_attributed_count,
                   coupon_assisted_conversion_count):
    divisor = D(max(1, attributed_conversion_count))
    coupon_share = D(coupon_assisted_conversion_count) * D(10000) / divisor
    new_share = D(new_customer_attributed_count) * D(10000) / divisor
    discount = D(PARTNER_TYPE_DISCOUNT_BPS[partner_type])
    raw = (D("0.55") * new_share
           + D("0.45") * (D(10000) - coupon_share)
           - discount)
    score = clamp(rhu_int(raw), 0, 10000)
    if score <= TIER_LOW_CEILING_BPS:
        tier = "LOW"
    elif score <= TIER_MEDIUM_CEILING_BPS:
        tier = "MEDIUM"
    else:
        tier = "HIGH"
    return score, tier


def point_in_time_fraud_score(cases):
    total = 0
    for case in cases:
        if case["state"] in POINT_IN_TIME_STATES:
            total += case["severity_weight"]
    return min(100, total)


def trailing_fraud_score(cases, now, parse_instant):
    total = D(0)
    for case in cases:
        detected = parse_instant(case["detected_at"])
        if detected is None:
            continue
        age_seconds = (now - detected).total_seconds()
        if age_seconds > TRAILING_WINDOW_DAYS * 86400:
            continue
        age_days = int(age_seconds // 86400)
        decay = D(1) - D("0.01") * D(age_days)
        if decay < D("0.20"):
            decay = D("0.20")
        state_factor = D("0.25") if case["state"] == "VERIFIED_CLEARED" else D(1)
        total += D(case["severity_weight"]) * decay * state_factor
    if total > D(100):
        total = D(100)
    return rhu1(total)


def network_fee_cents(net_before_fees_cents, fee_bps, flat_fee_cents,
                     conversion_count):
    percent_part = rhu_int(D(net_before_fees_cents) * D(fee_bps) / D(10000))
    return percent_part + flat_fee_cents * conversion_count


def withholding_cents(withholding_base_cents, withholding_bps):
    return rhu_int(D(withholding_base_cents) * D(withholding_bps) / D(10000))


def fee_variance(statement_fee_cents, batch_network_fee_cents):
    variance = statement_fee_cents - batch_network_fee_cents
    variance_bps = rhu_int(
        D(abs(variance)) * D(10000) / D(max(1, batch_network_fee_cents)))
    if variance == 0:
        status = "MATCHED"
    elif variance_bps <= VARIANCE_TOLERANCE_BPS:
        status = "ACCEPTED_WITH_VARIANCE"
    else:
        status = None
    return variance, variance_bps, status


def clawback_target_cents(payable_commission_cents_value, cumulative_returned,
                          order_total_cents):
    return rhu_int(D(payable_commission_cents_value) * D(cumulative_returned)
                   / D(order_total_cents))
