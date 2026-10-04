"""Domain thresholds — numeric constants from the PRD's calculation rules."""

CYCLE_CEILING_CENTS = {1: 100_000, 2: 200_000, 3: 300_000, 4: 400_000, 5: 500_000}

SAVINGS_PCT = {1: 0.02, 2: 0.03, 3: 0.04, 4: 0.05, 5: 0.05}

THRESHOLDS = {
    # Cost-of-credit rates (per week, of principal)
    "FLAT_RATE": 0.004,
    "REHAB_RATE_STEP_1": 0.001,
    "REHAB_RATE_STEP_2": 0.002,
    "REHAB_COUNT_THRESHOLD_1": 1,
    "REHAB_COUNT_THRESHOLD_2": 3,
    # Savings
    "MIN_SAVINGS_CENTS": 200,
    "LOCK_PCT": 0.10,
    # Ladder
    "REHAB_MULTIPLIER": 1.5,
    "MAX_CYCLE_LEVEL": 5,
    # Credit scoring
    "SCORE_BASE": 600,
    "SCORE_PER_ON_TIME": 10,
    "SCORE_PER_PROJECTED": 5,
    "SCORE_PER_MISSED": 30,
    "SCORE_PER_STRIKE": 15,
    "SCORE_PER_ATTENDED_MEETING": 2,
    "SCORE_FLOOR": 300,
    "SCORE_CEILING": 850,
    # Delinquency sweep
    "DELINQUENT_DAYS": 8,
    "DEFAULT_DAYS": 30,
    # Group formation
    "GROUP_SIZE": 5,
    "TRAINING_SESSIONS_REQUIRED": 2,
    "TRAINING_BUFFER_MINUTES": 30,
    # Branch tiers / capacity
    "TIER_MEDIUM_MIN": 200,
    "TIER_LARGE_MIN": 500,
    "MEMBER_CAP_SMALL": 60,
    "MEMBER_CAP_MEDIUM": 80,
    "MEMBER_CAP_LARGE": 100,
    "CENTER_CAP_SMALL": 3,
    "CENTER_CAP_MEDIUM": 4,
    "CENTER_CAP_LARGE": 5,
    # Loan terms
    "DEFAULT_TERM_WEEKS": 24,
    "ALLOWED_RESTRUCTURE_TERMS": (12, 24, 36, 48),
    "VOTING_WINDOW_DAYS": 7,
}

# Reference numbers for a cycle-1 100000c loan disbursed to a clean borrower
# (flat rate 0.004/week over 24 weeks, 2% savings percentage with the 200c floor).
# The exact product is 100000 * 1.096 / 24 = 4566.666..., which rounds half up
# to 4567 (not a half-tie):
#   weekly_installment_cents = round_half_up(100000 * 1.096 / 24) = 4567
#   savings_required_cents   = max(200, round_half_up(0.02 * 4567)) = 200
#   principal_outstanding    = 24 * 4567 = 109608
#   minimum legal collection = 200 + 1 = 201; the canonical collection is 4768
#   full payoff              = 200 + 109608 = 109808
TEST_DEFAULTS = {
    "CYCLE1_PRINCIPAL_CENTS": 100_000,
    "CYCLE1_WEEKLY_INSTALLMENT_CENTS": 4_567,
    "CYCLE1_SAVINGS_REQUIRED_CENTS": 200,
    "CYCLE1_OUTSTANDING_CENTS": 109_608,
    "CYCLE1_MIN_COLLECTION_CENTS": 4_768,
    "CYCLE1_FULL_PAYOFF_CENTS": 109_808,
    "CYCLE1_LOCKED_CENTS": 10_961,
    "CYCLE1_PROVISIONAL_SCORE": 720,
}

DEFAULT_MEETING_DAY_OF_WEEK = 1  # Tuesday
