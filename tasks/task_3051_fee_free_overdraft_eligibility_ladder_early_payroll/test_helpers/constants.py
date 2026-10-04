"""Domain thresholds and pinned test values.

Every constant below is stated verbatim in the PRD's business-logic prose:
scoring buckets and caps, ladder bands, the qualifying-amount boundary,
repayment timeliness, write-off aging, dispute deadlines, the adjustment
notice period, and the deposit-registration overlap buffer.
"""

# The instant the logical clock reads on a fresh deployment (PRD Section 2.10).
BASE_CLOCK = "2026-09-01T00:00:00Z"

# A system-minted resource id that no test ever creates.
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

# Scoring window and bucket thresholds (PRD Section 3.2).
SCORE_WINDOW_DAYS = 90
BUCKET_GE_6 = 400
BUCKET_GE_4 = 300
BUCKET_GE_2 = 150
TENURE_MAX_POINTS = 250
REPAY_POINT_EACH = 25
REPAY_CAP_COUNT = 10
ABUSE_PENALTY_EACH = 150
ABUSE_CAP_COUNT = 3
ELIGIBILITY_SCORE_THRESHOLD = 200

# Qualifying deposit boundary: PAYROLL and amount >= 10000 (inclusive).
QUALIFYING_MIN_CENTS = 10000

# Ladder caps (PRD Section 3.2), all boundaries inclusive.
SCORE_CAP_750 = 20000
SCORE_CAP_500 = 10000
SCORE_CAP_300 = 5000
SCORE_CAP_200 = 2000
REPAY_CAP_GE_5 = 20000
REPAY_CAP_GE_3 = 10000
REPAY_CAP_GE_1 = 5000
REPAY_CAP_ZERO = 2000
TENURE_CAP_GE_180 = 20000
TENURE_CAP_GE_90 = 10000
TENURE_CAP_GE_30 = 5000
TENURE_CAP_UNDER_30 = 2000

# Decrease notice period (PRD Section 3.3).
DECREASE_NOTICE_DAYS = 7

# Repayment timeliness and write-off aging (PRD Section 3.6).
ON_TIME_DAYS = 35
WRITE_OFF_AGING_DAYS = 60

# Dispute deadlines (PRD Section 3.9).
PROVISIONAL_BUSINESS_DAYS = 10
RESOLUTION_CALENDAR_DAYS = 45

# Early-posting reversal window (PRD Section 3.4).
REVERSAL_WINDOW_DAYS = 2

# Deposit-registration overlap buffer (PRD Section 3.4): distance of exactly
# three days between settlement dates is a conflict; four or more is allowed.
DEPOSIT_OVERLAP_BUFFER_DAYS = 3

TEST_DEFAULTS = {
    "PAYROLL_DEPOSIT_CENTS": 10000,
    "DEFAULT_SPONSOR_BANK_CODE": "SB-1",
}
