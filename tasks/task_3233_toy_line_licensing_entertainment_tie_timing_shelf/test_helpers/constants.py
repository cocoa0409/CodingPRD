"""Domain constants and thresholds named by the PRD.

The logical clock starts at exactly 2026-09-01T00:00:00Z before any set call
(PRD §2.5). Age grades run 36..168 months (PRD §3.3). The factory utilization
tier boundary is 80% (PRD §3.5). The embargo penalty tiers are 10% for a
retailer below 2 prior violations and 25% at 2 or more (PRD §3.7). Royalty
minimum-guarantee reconciliation happens every 4 closed quarters (PRD §3.2).
The closeout deep-discount damping knee is 50% (PRD §3.7).
"""

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

AGE_GRADE_MIN_MONTHS = 36
AGE_GRADE_MAX_MONTHS = 168

TIER0_UTILIZATION_MAX = 0.80
OVERTIME_PCT_PER_TIER = 0.15

REPEAT_OFFENDER_THRESHOLD = 2
FIRST_PENALTY_RATE = 0.10
REPEAT_PENALTY_RATE = 0.25

QUARTERS_PER_YEAR = 4

DEEP_DISCOUNT_KNEE = 0.50
DAMPING_DIVISOR = 2
