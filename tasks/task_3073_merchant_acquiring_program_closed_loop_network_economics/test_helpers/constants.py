"""Domain thresholds — numeric constants named by the requirements' calculations."""

# ─── Clock ────────────────────────────────────────────
# The server's logical clock before any administrative call.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# ─── Merchant pricing ─────────────────────────────────
# Month-to-date billed volume at which the volume tier turns from
# ACTIVITY to FIXED (fifty thousand dollars, in cents).
VOLUME_THRESHOLD_CENTS = 5_000_000
# FIXED-tier quoted rate is three quarters of the industry base.
FIXED_TIER_RATE_NUMERATOR = 3
FIXED_TIER_RATE_DENOMINATOR = 4

# ─── Acceptance gaps ──────────────────────────────────
ACCEPTANCE_GAP_DECLINE_MIN = 3
MIN_DECLINED_CENTS = 50

# ─── Reserves ─────────────────────────────────────────
RESERVE_FLOOR_BPS = 500
SWEEP_AT_ZERO = 0

# ─── Funding batches ──────────────────────────────────
BATCH_SEQ_START = 1
EPSILON_CENTS = 1

# ─── Trailing volume ──────────────────────────────────
WINDOW_DAYS = 90

# ─── Premium value funding ────────────────────────────
VALUE_FUND_SHARE_BPS = 4000
LOUNGE_PASS_COST_CENTS = 3500

# ─── Offers ───────────────────────────────────────────
AUDIENCE_QUORUM = 1
PROVISIONAL_DIVISOR = 2

# ─── Dispute points ───────────────────────────────────
POINTS_PER_DOLLAR = 1
MERCHANT_SHARE_BPS = 4000
MIN_POINTS_FLOOR = 0
DISPUTE_PRIORITY_AMOUNT_CENTS = 50000
DISPUTE_RESPONSE_MIN_AMOUNT_CENTS = 50000

# ─── Offer live-window clearance ──────────────────────
LIVE_WINDOW_CLEARANCE_DAYS = 1

# ─── Test defaults ────────────────────────────────────
TEST_DEFAULTS = {
    "INDUSTRY_BASE_RATE_BPS": 250,
    "NEGOTIATED_RATE_BPS": 175,
    "GROSS_VOLUME_CENTS": 500000,
    "REFUND_VOLUME_CENTS": 100000,
    "PRINCIPAL_FEE_CENTS": 1000000,
    "AUTHORISED_USER_COUNT": 2,
    "PER_USER_FEE_CENTS": 50000,
    "TRIGGER_AMOUNT_CENTS": 100000,
    "MEMBER_TRAILING_SPEND_CENTS": 100000,
    "POOL_INITIAL_FUNDED_CENTS": 500000,
}

THRESHOLDS = {
    "VOLUME_THRESHOLD_CENTS": VOLUME_THRESHOLD_CENTS,
    "ACCEPTANCE_GAP_DECLINE_MIN": ACCEPTANCE_GAP_DECLINE_MIN,
    "MIN_DECLINED_CENTS": MIN_DECLINED_CENTS,
    "RESERVE_FLOOR_BPS": RESERVE_FLOOR_BPS,
    "WINDOW_DAYS": WINDOW_DAYS,
    "VALUE_FUND_SHARE_BPS": VALUE_FUND_SHARE_BPS,
    "LOUNGE_PASS_COST_CENTS": LOUNGE_PASS_COST_CENTS,
    "AUDIENCE_QUORUM": AUDIENCE_QUORUM,
    "MERCHANT_SHARE_BPS": MERCHANT_SHARE_BPS,
    "DISPUTE_PRIORITY_AMOUNT_CENTS": DISPUTE_PRIORITY_AMOUNT_CENTS,
    "DISPUTE_RESPONSE_MIN_AMOUNT_CENTS": DISPUTE_RESPONSE_MIN_AMOUNT_CENTS,
    "EPSILON_CENTS": EPSILON_CENTS,
}