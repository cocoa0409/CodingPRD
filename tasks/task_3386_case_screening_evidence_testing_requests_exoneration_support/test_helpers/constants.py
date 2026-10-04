"""Domain thresholds and pinned instants stated in the PRD.

Every numeric literal below is traceable to PRD prose:
  screening maps / weights / anchors  -> section 3.1
  compensation rates / tiers / anchors -> section 3.8
  sample minimum                       -> section 3.5
  contact interval map                 -> section 3.7
  policy pattern threshold             -> section 3.9
  pagination bounds                    -> section 2.3
  logical clock default                -> section 2.4
"""

# The logical clock reads exactly this instant before any clock-setting call;
# the server never falls back to wall-clock time (PRD section 2.4).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# =============================================================================
# Screening priority score (PRD section 3.1)
# =============================================================================

# Factor -> integer maps, verbatim from the PRD narrative.
CLAIM_STRENGTH_POINTS = {"WEAK": 25, "MODERATE": 55, "STRONG": 80, "COMPELLING": 95}
EVIDENCE_POTENTIAL_POINTS = {
    "NONE_KNOWN": 0,
    "UNCERTAIN": 35,
    "LIKELY_STORED": 65,
    "CONFIRMED_STORED": 95,
}
HEALTH_URGENCY_POINTS = {"NONE": 0, "MODERATE": 45, "CRITICAL": 90}

# f_years := min(years_served * 100 / 30, 100) rounded to 2 decimals half-up:
# time served saturates at thirty years.
YEARS_SATURATION = 30

# Weight profiles; each sums to exactly 1.000.
WEIGHTS_STANDARD = {"claim": 0.425, "evidence": 0.275, "time": 0.185, "urgency": 0.115}
WEIGHTS_EXPEDITED = {"claim": 0.260, "evidence": 0.240, "time": 0.155, "urgency": 0.345}

# Rounding: each weighted product is rounded to 2 decimals half-up FIRST; the
# score is the plain sum of the four rounded products with no final re-round
# (PRD section 2.10).
SCORE_DECIMALS = 2

# PRD worked anchor: STRONG / LIKELY_STORED / 7 years / CRITICAL yields a time
# factor of 23.33 and scores of 66.55 (STANDARD) and 71.07 (EXPEDITED).
ANCHOR_CLAIM_STRENGTH = "STRONG"
ANCHOR_EVIDENCE_POTENTIAL = "LIKELY_STORED"
ANCHOR_YEARS_SERVED = 7
ANCHOR_HEALTH_URGENCY = "CRITICAL"
ANCHOR_TIME_FACTOR = 23.33
ANCHOR_SCORE_STANDARD = 66.55
ANCHOR_SCORE_EXPEDITED = 71.07
ANCHOR_STANDARD_PARTS = (34.00, 17.88, 4.32, 10.35)
ANCHOR_EXPEDITED_PARTS = (20.80, 15.60, 3.62, 31.05)

# =============================================================================
# Compensation award (PRD section 3.8)
# =============================================================================

FLAT_RATE_CENTS_PER_YEAR = 5_000_000      # provisional: flat per claimed year
TIER1_YEARS = 5                           # first 5 verified years at tier-1 rate
TIER1_RATE_CENTS = 5_000_000
TIER2_RATE_CENTS = 7_500_000              # each verified year beyond 5
FEE_REIMBURSEMENT_CAP_CENTS = 2_500_000   # fees reimbursed after the cap
DAYS_PER_YEAR = 365                       # verified_years := floor(days / 365)

# PRD worked anchors (pin the evaluation order):
#   conviction 2016-03-15 -> exoneration 2026-11-20 is 3902 days -> 10 years.
#   With 10 years claimed, 10% enhancement, cap 100,000,000, fees 3,000,000:
#     PROVISIONAL    = 50,000,000
#     FINAL_VERIFIED = min(62,500,000 * 1.10, cap) + min(fees, 2,500,000)
#                    = 68,750,000 + 2,500,000 = 71,250,000
#   Same facts with cap 60,000,000: 60,000,000 + 2,500,000 = 62,500,000.
ANCHOR_CONVICTION_DATE = "2016-03-15T00:00:00Z"
ANCHOR_EXONERATION_CLOCK = "2026-11-20T00:00:00Z"
ANCHOR_VERIFIED_DAYS = 3902
ANCHOR_VERIFIED_YEARS = 10
ANCHOR_YEARS_CLAIMED = 10
ANCHOR_ENHANCEMENT_PCT = 10
ANCHOR_CAP_CENTS = 100_000_000
ANCHOR_BITING_CAP_CENTS = 60_000_000
ANCHOR_FEES_CENTS = 3_000_000
ANCHOR_PROVISIONAL_CENTS = 50_000_000
ANCHOR_TIERED_BASE_CENTS = 62_500_000
ANCHOR_ENHANCED_BASE_CENTS = 68_750_000
ANCHOR_FINAL_AWARD_CENTS = 71_250_000
ANCHOR_CAPPED_FINAL_AWARD_CENTS = 62_500_000

# =============================================================================
# Sample ledger (PRD section 3.5)
# =============================================================================

# Reservation requires remaining >= required AND remaining >= 5 ng; below
# 5 ng remaining the item's testing_status derives to SAMPLE_EXHAUSTED.
MIN_TESTABLE_NG = 5

# =============================================================================
# Contact-overdue sweep (PRD section 3.7)
# =============================================================================

# Interval a case may go silent, keyed by status; null (None) when CLOSED.
# Overdue is STRICT: days_since > interval; exactly at the interval is not
# overdue.
CONTACT_INTERVAL_DAYS = {
    "OPEN": 90,
    "INVESTIGATION": 90,
    "TESTING": 60,
    "LITIGATION": 30,
    "EXONERATED": 14,
    "CLOSED": None,
}
CONTACT_INTERVAL_OPEN = 90
CONTACT_INTERVAL_INVESTIGATION = 90
CONTACT_INTERVAL_TESTING = 60
CONTACT_INTERVAL_LITIGATION = 30
CONTACT_INTERVAL_EXONERATED = 14

# CLOCK_DEFAULT + exactly 90 / 91 days: the OPEN-interval boundary pair.
CLOCK_DEFAULT_PLUS_90D = "2026-11-30T00:00:00Z"
CLOCK_DEFAULT_PLUS_91D = "2026-12-01T00:00:00Z"

# =============================================================================
# Policy pattern threshold (PRD section 3.9)
# =============================================================================

# SUBMIT_DRAFT requires pattern_case_count >= 3 (inclusive).
POLICY_PATTERN_THRESHOLD = 3

# =============================================================================
# Pagination (PRD section 2.3)
# =============================================================================

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Collected THRESHOLDS view for tests that iterate thresholds generically.
THRESHOLDS = {
    "YEARS_SATURATION": YEARS_SATURATION,
    "MIN_TESTABLE_NG": MIN_TESTABLE_NG,
    "POLICY_PATTERN_THRESHOLD": POLICY_PATTERN_THRESHOLD,
    "CONTACT_INTERVAL_OPEN": CONTACT_INTERVAL_OPEN,
    "CONTACT_INTERVAL_INVESTIGATION": CONTACT_INTERVAL_INVESTIGATION,
    "CONTACT_INTERVAL_TESTING": CONTACT_INTERVAL_TESTING,
    "CONTACT_INTERVAL_LITIGATION": CONTACT_INTERVAL_LITIGATION,
    "CONTACT_INTERVAL_EXONERATED": CONTACT_INTERVAL_EXONERATED,
    "FLAT_RATE_CENTS_PER_YEAR": FLAT_RATE_CENTS_PER_YEAR,
    "TIER1_YEARS": TIER1_YEARS,
    "TIER1_RATE_CENTS": TIER1_RATE_CENTS,
    "TIER2_RATE_CENTS": TIER2_RATE_CENTS,
    "FEE_REIMBURSEMENT_CAP_CENTS": FEE_REIMBURSEMENT_CAP_CENTS,
    "DAYS_PER_YEAR": DAYS_PER_YEAR,
}
