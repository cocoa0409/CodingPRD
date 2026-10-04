"""
Domain thresholds and platform constants.

Every numeric constant the PRD states: commission bands, per-assignment fee
tiers, review/dispute/vetting windows, payout floors, the concurrency cap and
the qualification-rate cascade thresholds.
"""

# ─── Task funding arithmetic ─────────────────────────────────────────────────
COMMISSION_RATE_LOW = 0.20
COMMISSION_RATE_MID = 0.15
COMMISSION_RATE_HIGH = 0.10
COMMISSION_TIER_MID_CENTS = 10_000   # gross pool at/above this takes 0.15
COMMISSION_TIER_HIGH_CENTS = 50_000  # gross pool at/above this takes 0.10

FEE_PER_ASSIGNMENT_LOW_CENTS = 5     # pre-fee amount below FEE_TIER_CENTS
FEE_PER_ASSIGNMENT_HIGH_CENTS = 3    # pre-fee amount at/above FEE_TIER_CENTS
FEE_TIER_CENTS = 20_000

# ─── Worker earning ──────────────────────────────────────────────────────────
WORKER_COMMISSION_RATE = 0.10

# ─── Windows ─────────────────────────────────────────────────────────────────
REVIEW_WINDOW_HOURS = 72
HOLD_DAYS = 3
REVIEW_WINDOW_DAYS = 30
DISPUTE_WINDOW_HOURS = 72

# ─── Rejection-rate thresholds and risk weights ──────────────────────────────
ABUSE_FLAG_THRESHOLD_PCT = 20
FRAUD_REVIEW_THRESHOLD_PCT = 40
SUSPENSION_ABUSE_SCORE = 10
W_REJECTION = 1.2
W_DISTINCT_WORKER = 3.0
W_SPEED = 0.5
ABUSE_DECAY_DAYS = 7
BONUS_ABUSE_POINTS = 2

# ─── Payout floors (cents, by worker country) ────────────────────────────────
PAYOUT_MIN_US_CENTS = 100
PAYOUT_MIN_IN_PH_CENTS = 500
PAYOUT_MIN_BR_CENTS = 1000
PAYOUT_MIN_DEFAULT_CENTS = 500

# ─── Concurrency ─────────────────────────────────────────────────────────────
# The PRD names the per-worker concurrency cap but never gives it a number
# (PRD §3.3 mentions only the symbol `MAX_CONCURRENT_ASSIGNMENTS`). Assertions
# therefore never depend on its absolute value: they probe the server's own
# cap by accepting until it refuses with ERR_CONCURRENCY_LIMIT_EXCEEDED, then
# release one slot by expiry so exactly one slot is provably free. This bound
# only stops that probe from running forever.
CONCURRENCY_PROBE_LIMIT = 50

# ─── Exam defaults ───────────────────────────────────────────────────────────
EXAM_MAX_ATTEMPTS_DEFAULT = 3
EXAM_COOLDOWN_DAYS_DEFAULT = 0

# ─── Friendly constants ──────────────────────────────────────────────────────
HIT_SLOT_DURATION_MINUTES = 60
HIT_HALF_WINDOW_MINUTES = 30
LONG_HOLD_MINUTES = 300
CASCADE_DRAIN_MINUTES = 600
CLOCK_EPOCH = "2026-09-01T00:00:00Z"

# ─── Test defaults ───────────────────────────────────────────────────────────
TEST_DEFAULTS = {
    "REQUESTER_NAME": "Test Requester",
    "WORKER_NAME": "Test Worker",
    "WORKER_COUNTRY": "US",
    "REWARD_CENTS": 100,
    "MAX_ASSIGNMENTS": 1,
    "ASSIGNMENT_DURATION_MINUTES": HIT_SLOT_DURATION_MINUTES,
    "TIME_LIMIT_MINUTES": 300,
    "DEPOSIT_CENTS": 5_000,
}