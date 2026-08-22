"""Domain thresholds, rates and the fixed reference instants used by the suite."""

# ─── The logical jobsite clock ────────────────────────────────────────────
# Before the first repositioning call the logical clock reads exactly this.
CLOCK_START = "2026-08-01T00:00:00.000Z"

# ─── Change-order pricing ─────────────────────────────────────────────────
MARKUP_TIER_1_CEILING = 5000.00
MARKUP_TIER_2_CEILING = 25000.00
MARKUP_RATE_LOW_TIER = 0.20
MARKUP_RATE_MID_TIER = 0.15
MARKUP_RATE_HIGH_TIER = 0.10

CONTINGENCY_TIER_1_CEILING = 10000.00
CONTINGENCY_TIER_2_CEILING = 50000.00
CONTINGENCY_RATE_NONE = 0.00
CONTINGENCY_RATE_MID = 0.03
CONTINGENCY_RATE_HIGH = 0.05

GENERAL_CONDITIONS_DAY_RATE = 485.00

# ─── Change-order negotiation ─────────────────────────────────────────────
MAX_REVISION_ROUNDS = 3
CLIENT_RESPONSE_DAYS = 14

# ─── Budget posture ───────────────────────────────────────────────────────
ALLOWANCE_OVERRUN_PCT = 0.02

# ─── Schedule ─────────────────────────────────────────────────────────────
FABRICATION_BUFFER_DAYS = 3
JOBSITE_CURE_BUFFER_DAYS = 1

# ─── Warranty ─────────────────────────────────────────────────────────────
WARRANTY_BASE_DAYS = 365
SYSTEMS_TRADE_DAYS = 730
SYSTEMS_TRADES = ("PLUMBING", "ELECTRICAL", "HVAC")
EXCLUDED_WARRANTY_CATEGORIES = ("HOMEOWNER_DAMAGE", "NORMAL_WEAR")

# ─── Defect response clocks (whole days, keyed by severity) ───────────────
DEFECT_RESPONSE_DAYS = {
    "LIFE_SAFETY": 1,
    "FUNCTIONAL": 7,
    "COSMETIC": 30,
}

# ─── Values the suite reuses when standing a job up ───────────────────────
TEST_DEFAULTS = {
    "BASE_CONTRACT_AMOUNT": 900000.00,
    "ALLOWANCE_AMOUNT": 18000.00,
    "SELECTION_DEADLINE": "2026-12-01T00:00:00.000Z",
    "TARGET_SUBSTANTIAL_COMPLETION": "2027-06-30T00:00:00.000Z",
    "RETAINAGE_PCT": 0.05,
    "MAX_CUMULATIVE_DRAW_PCT": 0.90,
    "REVIEW_WINDOW_DAYS": 10,
    "PERIOD_START": "2026-08-01T00:00:00.000Z",
    "PERIOD_END": "2026-08-31T00:00:00.000Z",
    "FRAME_TASK_START": "2026-09-01T00:00:00.000Z",
    "FRAME_TASK_FINISH": "2026-10-15T00:00:00.000Z",
    "BUILDER_FEE_PCT": 0.18,
}

# Money tolerance: every monetary figure is carried to exactly two decimals.
MONEY_TOLERANCE = 0.005
