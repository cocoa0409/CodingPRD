"""Calculation rules C1-C8 (PRD 3.3, 3.5, 3.7, 3.8, 3.9 / scaffold 1.3).

Money is always integer cents computed with Decimal and ROUND_HALF_UP; no
float arithmetic ever touches a monetary value.
"""
from decimal import Decimal, ROUND_HALF_UP

# --- C1 offer_line_pricing -------------------------------------------------
OFFER_TTL_MINUTES = 30

# --- C3 agency_incentive_accrual ------------------------------------------
TIER_1_CEILING_CENTS = 5000000
TIER_2_CEILING_CENTS = 20000000
TIER_1_RATE = Decimal("0.010")
TIER_2_RATE = Decimal("0.025")
TIER_3_RATE = Decimal("0.040")
MAX_NEGOTIATION_ROUNDS = 3

# --- C5 certification_readiness_score -------------------------------------
MANDATORY_TEST_WEIGHT = 3
OPTIONAL_TEST_WEIGHT = 1
CERT_MIN_READINESS = 80

# --- C6 refund_settlement -------------------------------------------------
REFUND_FEE_LOW_CENTS = 2500
REFUND_FEE_MID_CENTS = 7500
REFUND_FEE_MID_FLOOR_CENTS = 50000
REFUND_FEE_HIGH_FLOOR_CENTS = 200000
REFUND_FEE_HIGH_RATE = Decimal("0.05")

# --- C8 connectivity_slot_occupation --------------------------------------
TEST_TEARDOWN_BUFFER_MINUTES = 15
MAX_CONCURRENT_TESTS_PER_ENV = 2

CONTENT_TIER_RANKS = {"FULL": 3, "STANDARD": 2, "RESTRICTED": 1}

TIER_ORDER = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}
TIER_RATES = {"TIER_1": TIER_1_RATE, "TIER_2": TIER_2_RATE, "TIER_3": TIER_3_RATE}

ZERO = Decimal(0)


def round_half_up(value):
    """Round a Decimal to a whole integer, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def content_tier_rank(content_tier):
    return CONTENT_TIER_RANKS[content_tier]


# ---------------------------------------------------------------------------
# C1 : offer_line_pricing  (round per line, THEN sum)
# ---------------------------------------------------------------------------
def line_net_amount(list_amount_cents, discount_pct, markup_pct):
    """Step 2 bundle discount (exact), step 3 markup then round once."""
    discounted = Decimal(list_amount_cents)
    if discount_pct is not None:
        discounted = discounted * (Decimal(1) - Decimal(discount_pct))
    return round_half_up(discounted * (Decimal(1) + Decimal(markup_pct)))


# ---------------------------------------------------------------------------
# C2 : surcharge_amount  (inclusive threshold, round before clamping)
# ---------------------------------------------------------------------------
def surcharge_line(scope_base, rule):
    """Returns (raw, clamped) or None when the rule does not fire."""
    if scope_base < rule["threshold_cents"]:
        return None
    raw = round_half_up(Decimal(scope_base) * Decimal(rule["rate_pct"]))
    clamped = min(max(raw, rule["min_cents"]), rule["max_cents"])
    return raw, clamped


# ---------------------------------------------------------------------------
# C3 : agency_incentive_accrual  (marginal bands, cap, round once)
# ---------------------------------------------------------------------------
def incentive_tier_for(revenue_cents):
    if revenue_cents >= TIER_2_CEILING_CENTS:
        return "TIER_3"
    if revenue_cents >= TIER_1_CEILING_CENTS:
        return "TIER_2"
    return "TIER_1"


def agency_incentive_accrual(revenue_cents, agreed_incentive_pct,
                            incentive_multiplier, incentive_cap_cents):
    """Returns (incentive_accrued_cents, incentive_tier)."""
    revenue = Decimal(revenue_cents)
    band_1 = min(revenue, Decimal(TIER_1_CEILING_CENTS))
    band_2 = min(max(revenue - Decimal(TIER_1_CEILING_CENTS), ZERO),
                 Decimal(TIER_2_CEILING_CENTS - TIER_1_CEILING_CENTS))
    band_3 = max(revenue - Decimal(TIER_2_CEILING_CENTS), ZERO)
    marginal = band_1 * TIER_1_RATE + band_2 * TIER_2_RATE + band_3 * TIER_3_RATE
    pct = Decimal(agreed_incentive_pct) if agreed_incentive_pct is not None else ZERO
    scaled = marginal * Decimal(incentive_multiplier) * (pct / TIER_2_RATE)
    capped = min(scaled, Decimal(incentive_cap_cents))
    return round_half_up(capped), incentive_tier_for(revenue_cents)


def tier_ranks_below(new_tier, old_tier):
    return TIER_ORDER[new_tier] < TIER_ORDER[old_tier]


# ---------------------------------------------------------------------------
# C4 : distribution_cost_per_booking  (two variants)
# ---------------------------------------------------------------------------
def cost_per_booking_flat(monthly_platform_fee_cents, booking_count):
    if booking_count == 0:
        return 0
    return round_half_up(Decimal(monthly_platform_fee_cents) / Decimal(booking_count))


def activity_cost(channel, paid_orders, signed_agreements):
    total = 0
    for order in paid_orders:
        total += channel["per_message_cost_cents"] * order["message_count"]
        total += channel["per_segment_fee_cents"] * order["segment_count"]
    for agreement in signed_agreements:
        total += agreement["incentive_accrued_cents"]
    return total


def cost_per_booking_activity(activity_cost_cents, booking_count):
    if booking_count == 0:
        return 0
    return round_half_up(Decimal(activity_cost_cents) / Decimal(booking_count))


# ---------------------------------------------------------------------------
# C5 : certification_readiness_score  (STRICT / PROVISIONAL)
# ---------------------------------------------------------------------------
def _test_weight(test):
    return MANDATORY_TEST_WEIGHT if test["is_mandatory"] else OPTIONAL_TEST_WEIGHT


def _weighted_mean(tests):
    weight_total = 0
    score_total = 0
    for test in tests:
        weight = _test_weight(test)
        weight_total += weight
        score_total += (test["score"] or 0) * weight
    if weight_total == 0:
        return 0
    return round_half_up(Decimal(score_total) / Decimal(weight_total))


def readiness_scores(tests, mandatory_failed_count):
    """Returns (strict, provisional) over PASSED/FAILED tests only."""
    considered = [t for t in tests if t["status"] in ("PASSED", "FAILED")]
    if mandatory_failed_count > 0 or not considered:
        strict = 0
    else:
        strict = _weighted_mean(considered)
    included = [t for t in considered
                if not (t["is_mandatory"] and t["status"] == "FAILED")]
    provisional = _weighted_mean(included) if included else 0
    return strict, provisional


# ---------------------------------------------------------------------------
# C6 : refund_settlement  (pinned step order 1-4)
# ---------------------------------------------------------------------------
def cancellation_fee(refundable_base_cents):
    if refundable_base_cents < REFUND_FEE_MID_FLOOR_CENTS:
        return REFUND_FEE_LOW_CENTS
    if refundable_base_cents < REFUND_FEE_HIGH_FLOOR_CENTS:
        return REFUND_FEE_MID_CENTS
    return round_half_up(Decimal(refundable_base_cents) * REFUND_FEE_HIGH_RATE)


def refund_settlement(refundable_base_cents, agreement_tier):
    fee = cancellation_fee(refundable_base_cents)
    total = max(refundable_base_cents - fee, 0)
    if agreement_tier is None:
        clawback = 0
    else:
        clawback = round_half_up(Decimal(total) * TIER_RATES[agreement_tier])
    return refundable_base_cents, fee, total, clawback


# ---------------------------------------------------------------------------
# C7 : disclosure_completeness  (order-insensitive set difference)
# ---------------------------------------------------------------------------
def missing_disclosure_codes(required_codes, acknowledged_codes):
    acked = set(acknowledged_codes or [])
    return [code for code in (required_codes or []) if code not in acked]


# ---------------------------------------------------------------------------
# C8 : connectivity_slot_occupation  (two closed-interval rules)
# ---------------------------------------------------------------------------
def intervals_share_instant(start_a, end_a, start_b, end_b):
    """Closed intervals: touching endpoints DO share an instant."""
    return start_a <= end_b and start_b <= end_a
