"""Domain thresholds and schedule constants from the PRD (§3.2–§3.9)."""

# --- Application fee schedule (PRD §3.2) ---------------------------------
# Per-item fee = category base + round_half_up(rate * item cost in cents);
# the per-item rounding happens before the sum, and reordering the rounding
# is a specification violation (PRD §2.6, §3.2).
FEE_BASE_CENTS = {
    "EXTERIOR_ALTERATION": 15000,
    "ADDITION": 30000,
    "NEW_CONSTRUCTION": 50000,
    "DEMOLITION": 25000,
    "RELOCATION": 40000,
    "SITE_WORK": 10000,
}
FEE_RATES = {
    "EXTERIOR_ALTERATION": 0.004,
    "ADDITION": 0.005,
    "NEW_CONSTRUCTION": 0.006,
    "DEMOLITION": 0.003,
    "RELOCATION": 0.005,
    "SITE_WORK": 0.002,
}
HEARING_SURCHARGE_CENTS = 20000  # added after the per-item sum when COMMISSION

# --- Review track threshold (PRD §3.3) ------------------------------------
COMMISSION_REVIEW_THRESHOLD_CENTS = 1000000  # inclusive >= boundary

# --- Civil penalty schedule (PRD §3.8) -------------------------------------
PENALTY_TIER1_DAILY_CENTS = 10000   # days 1..30
PENALTY_TIER2_DAILY_CENTS = 20000   # days 31..60
PENALTY_TIER3_DAILY_CENTS = 50000   # days 61+
PENALTY_TIER1_DAYS = 30
PENALTY_TIER2_DAYS = 30
PENALTY_CAP_PCT_OF_ASSESSED_VALUE = 0.10
CURE_WINDOW_DAYS = 30
ESCALATION_THRESHOLD_DAYS = 60      # referral requires strictly more than 60

# --- Demolition delay schedule (PRD §3.7) ----------------------------------
BASE_DELAY_DAYS = {"LOCAL": 90, "LANDMARK": 180, "ICONIC": 365}
POSTPONEMENT_EXTENSION_DAYS = 30
MAX_POSTPONEMENTS = 2
HARDSHIP_FILING_CUTOFF_DAYS = 30
HARDSHIP_LIFT_DAYS = 10

# --- Other windows (PRD §3.4, §3.6, §3.9) ----------------------------------
NOTICE_PERIOD_DAYS = 15             # inclusive boundary
APPEAL_WINDOW_DAYS = 30             # inclusive boundary
RESUBMISSION_WINDOW_DAYS = 90       # inclusive boundary
CERTIFICATE_COMMENCE_DAYS = 365

# --- Withdrawal refund percentages (PRD §3.5) --------------------------------
REFUND_PCT_EARLY = 1.00             # SUBMITTED / UNDER_STAFF_REVIEW / INCOMPLETE
REFUND_PCT_POST_ACCEPTANCE = 0.50   # ACCEPTED / HEARING_SCHEDULED / HEARING_DEFERRED
REFUND_PCT_POST_OPEN = 0.00         # HEARING_OPEN

# --- Logical clock anchors ---------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"
MEETING_DAY = "2026-09-01T00:00:00Z"
NOTICE_STANDARD = "2026-08-10T00:00:00Z"   # 22 days before MEETING_DAY
NOTICE_BOUNDARY = "2026-08-17T00:00:00Z"   # exactly 15 days before MEETING_DAY
