"""Pinned platform constants (SCAFFOLD.yaml §1.3 constants blocks) and the
logical clock.

The platform runs on a logical clock, never wall-clock time. On startup the
clock reads exactly 2026-09-01T00:00:00Z and never falls back to real time.
"""

# --- HIT funding (calculation: hit_funds_required) -------------------------
COMMISSION_RATE_LOW = "0.20"
COMMISSION_RATE_MID = "0.15"
COMMISSION_RATE_HIGH = "0.10"
COMMISSION_TIER_MID_CENTS = 10000
COMMISSION_TIER_HIGH_CENTS = 50000
FEE_PER_ASSIGNMENT_LOW_CENTS = 5
FEE_PER_ASSIGNMENT_HIGH_CENTS = 3
FEE_TIER_CENTS = 20000

# --- Worker earnings (calculation: worker_net_earning) ---------------------
WORKER_COMMISSION_RATE = "0.10"
BONUS_ABUSE_POINTS = 2

# --- Requester rejection behaviour (calculation: requester_rejection_rate) --
REVIEW_WINDOW_DAYS = 30
FRAUD_REVIEW_THRESHOLD_PCT = 40
ABUSE_FLAG_THRESHOLD_PCT = 20

# --- Abuse risk score (calculation: requester_risk_score) ------------------
W_REJECTION = "1.2"
W_DISTINCT_WORKER = "3.0"
W_SPEED = "0.5"
ABUSE_DECAY_DAYS = 7

# --- Review / assignment windows -------------------------------------------
REVIEW_WINDOW_HOURS = 72

# --- Payouts (calculation: payout_threshold_by_country) --------------------
PAYOUT_MIN_US_CENTS = 100
PAYOUT_MIN_IN_PH_CENTS = 500
PAYOUT_MIN_BR_CENTS = 1000
HOLD_DAYS = 3

# --- Constants named by the scaffold/PRD but not pinned to a number there.
# These are the only two windows the spec leaves unquantified; the values are
# the platform's operating defaults.
MAX_CONCURRENT_ASSIGNMENTS = 5
DISPUTE_WINDOW_HOURS = 168

# --- Payment-method eligibility per country ---------------------------------
ELIGIBLE_PAYMENT_METHODS = {
    "US": {"BANK_TRANSFER", "PAYPAL", "GIFT_CARD"},
    "IN": {"BANK_TRANSFER", "PAYPAL"},
    "PH": {"BANK_TRANSFER", "PAYPAL"},
    "BR": {"BANK_TRANSFER", "PAYPAL"},
}
DEFAULT_ELIGIBLE_PAYMENT_METHODS = {"BANK_TRANSFER", "PAYPAL"}

PAYOUT_METHODS = {"BANK_TRANSFER", "PAYPAL", "GIFT_CARD"}
WORKER_COUNTRIES = {"US", "IN", "PH", "BR"}

# --- Logical clock ----------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"


class Clock:
    """A single mutable logical instant shared by every request."""

    def __init__(self):
        self.now = CLOCK_DEFAULT_UTC

    def set(self, value: str) -> None:
        self.now = value

    def get(self) -> str:
        return self.now


clock = Clock()