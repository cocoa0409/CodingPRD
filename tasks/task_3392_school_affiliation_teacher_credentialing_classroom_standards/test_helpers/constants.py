"""Domain constants — every value traced to PRD.md prose (section cited per block).

Nothing in this module is assumed: each numeric threshold is either stated
verbatim in the PRD or is part of the frozen test-edition catalog payload
whose value the tests themselves choose when they create the catalog.
"""

# ---------------------------------------------------------------------------
# API mounting (PRD section 1: "mounted under /society"; PRD section 4 table)
# ---------------------------------------------------------------------------
API_PREFIX = "/society"
CLOCK_PATH = "/society/_clock/set_current_utc"

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.5: "the logical clock reads exactly
# 2026-09-01T00:00:00Z, and the server must never fall back to wall-clock
# time")
# ---------------------------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
CLOCK_START_DATE = "2026-09-01"

# ---------------------------------------------------------------------------
# Brand rule (PRD section 3.2: "the constant METHOD_NAME, whose value is
# 'Montessori'")
# ---------------------------------------------------------------------------
METHOD_NAME = "Montessori"

# ---------------------------------------------------------------------------
# Annual membership dues schedule (PRD section 3.2):
#   "40000 cents for AFFILIATE (an APPLICANT school quotes the AFFILIATE
#    schedule), 90000 cents for MEMBER, and 150000 cents for ACCREDITED"
#   "1500 cents for each of the first 100 students, 1200 cents for each
#    student from 101 through 300, and 900 cents for each student beyond 300"
#   "a surcharge of 8000 cents per classroom"
#   "floored at 60000 cents before being capped at 1500000 cents; the floor
#    applies before the cap"
# ---------------------------------------------------------------------------
BASE_DUES_AFFILIATE_CENTS = 40000
BASE_DUES_MEMBER_CENTS = 90000
BASE_DUES_ACCREDITED_CENTS = 150000
BASE_DUES_CENTS = {
    "APPLICANT": BASE_DUES_AFFILIATE_CENTS,  # APPLICANT quotes AFFILIATE schedule
    "AFFILIATE": BASE_DUES_AFFILIATE_CENTS,
    "MEMBER": BASE_DUES_MEMBER_CENTS,
    "ACCREDITED": BASE_DUES_ACCREDITED_CENTS,
}
TIER1_UP_TO = 100
TIER1_RATE_CENTS = 1500
TIER2_UP_TO = 300
TIER2_RATE_CENTS = 1200
TIER3_RATE_CENTS = 900
PER_CLASSROOM_SURCHARGE_CENTS = 8000
MIN_DUES_CENTS = 60000
MAX_DUES_CENTS = 1500000

# Worked anchors pinned in PRD section 3.2 prose:
#   AFFILIATE/0 students/1 room  -> raw 48000  -> 60000  (floor)
#   MEMBER/250 students/4 rooms  -> 452000
#   AFFILIATE/100 students/1 room -> 198000
#   AFFILIATE/101 students/1 room -> 199200  (101st student bills at 1200c)
#   ACCREDITED/1500 students/20 rooms -> raw 1780000 -> 1500000 (cap)
DUES_ANCHOR_FLOOR_CENTS = 60000
DUES_ANCHOR_MEMBER_250_4_CENTS = 452000
DUES_ANCHOR_AFFILIATE_100_1_CENTS = 198000
DUES_ANCHOR_AFFILIATE_101_1_CENTS = 199200
DUES_ANCHOR_CAP_CENTS = 1500000

# ---------------------------------------------------------------------------
# Credential renewal fee (PRD section 3.5): "the expected amount is 8500
# cents, plus a 5000-cent late fee when the credential is LAPSED"
# ---------------------------------------------------------------------------
RENEWAL_BASE_FEE_CENTS = 8500
RENEWAL_LATE_FEE_CENTS = 5000
RENEWAL_FEE_WHEN_LAPSED_CENTS = RENEWAL_BASE_FEE_CENTS + RENEWAL_LATE_FEE_CENTS  # 13500

# ---------------------------------------------------------------------------
# Supervisor capacity (PRD section 3.4): "the credential must be supervising
# fewer than 3 other ACTIVE placements — exactly 3 supervised placements is
# allowed, and a fourth is rejected"
# ---------------------------------------------------------------------------
SUPERVISOR_MAX_ACTIVE_PLACEMENTS = 3

# ---------------------------------------------------------------------------
# Classroom clearance cycle window (PRD section 3.7): "no audit whose
# observed_at date falls inside the trailing 12 calendar months, inclusive
# of today, has verdict NONCOMPLIANT"
# ---------------------------------------------------------------------------
CLEARANCE_CYCLE_WINDOW_MONTHS = 12

# ---------------------------------------------------------------------------
# Rounding rules (PRD section 2.9): ratios 2dp half-up; materials per-group
# 2dp half-up then exact mean, stored 4dp half-up; CE hours 1dp exact;
# money integer cents.
# ---------------------------------------------------------------------------
RATIO_DECIMALS = 2
MATERIALS_GROUP_DECIMALS = 2
MATERIALS_SCORE_DECIMALS = 4
CE_HOURS_DECIMALS = 1

# ---------------------------------------------------------------------------
# Pagination defaults (PRD section 2.3): limit defaults 10, min 1, max 100;
# offset defaults 0.
# ---------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ---------------------------------------------------------------------------
# A second syntactically-valid-but-unallocated UUID for tests that need two
# distinct unknown ids in one call (the framework exports the first).
# ---------------------------------------------------------------------------
NON_EXISTENT_UUID_ALT = "00000000-0000-4000-8000-000000000000"
