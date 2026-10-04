"""Domain constants — thresholds, fees, scores, dates, canonical identities.

Every value below is pinned by PRD prose (§2.4, §2.7, §3.1-§3.9) and diffed
against the PRD text; the precomputed fee/score/percentage literals are the
values the PRD's own rounding rules produce for the standard fixture shapes.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4: default reading 2026-09-01T00:00:00Z; monotonic)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Clock setpoints exercised by the test recipes.
CLOCK_REGISTRATION_OPEN = "2026-09-01T00:00:00Z"     # opens the standard window
CLOCK_SUSPENSION_DAY = "2026-09-05T00:00:00Z"        # sanction resolved here
CLOCK_LATE_FEE_TIER = "2026-09-20T00:00:00Z"         # inside the 14-day late window
CLOCK_BEFORE_DEADLINE_1S = "2026-09-30T23:59:59Z"    # one second before deadline
CLOCK_AT_DEADLINE = "2026-10-01T00:00:00Z"           # sweep closes window (>=)
CLOCK_REGISTRATION_CLOSED = "2026-10-02T00:00:00Z"   # after deadline, before testing
CLOCK_SUSPENSION_LIFT_MINUS_1 = "2026-10-04T00:00:00Z"
CLOCK_SUSPENSION_LIFT_EXACT = "2026-10-05T00:00:00Z"  # 2026-09-05 + 30 days
CLOCK_TESTING_STARTS = "2026-10-10T09:00:00Z"
CLOCK_SCORING = "2026-10-13T00:00:00Z"               # past testing_ends_at; SAT sweep
CLOCK_SUSPENDED_ATTEMPT = "2026-10-14T00:00:00Z"     # inside cooldown AND suspension
CLOCK_COOLDOWN_BLOCKED = "2026-10-26T00:00:00Z"      # 13 days after FAILED submit
CLOCK_COOLDOWN_EXACT = "2026-10-27T00:00:00Z"        # submitted_at + 14d (allowed)
CLOCK_FM2_WINDOW_OPEN = "2026-11-01T00:00:00Z"
CLOCK_SESSION_HELD = "2026-11-06T00:00:00Z"          # past APC session ends_at
CLOCK_2027_WINDOW_OPEN = "2027-05-01T00:00:00Z"
CLOCK_2027_SCORING = "2027-06-13T00:00:00Z"
CLOCK_ASA_ADMIT_JULY = "2027-07-15T00:00:00Z"        # admission month 7 for proration

# ---------------------------------------------------------------------------
# Exam scoring (PRD §3.3: raw 0..60; scaled = round_half_up(raw/60*10, 1))
# ---------------------------------------------------------------------------
MAX_RAW_SCORE = 60
RAW_SCORE_PROJECTED_PASS = 37        # scaled 6.2
RAW_SCORE_AT_MARK = 39               # scaled 6.5 — equality passes
RAW_SCORE_BELOW_MARK = 38            # scaled 6.3
RAW_SCORE_HALF_UP = 33               # scaled exactly 5.5
RAW_SCORE_TRUNCATING = 32            # scaled 5.333... -> 5.3
RAW_SCORE_HIGH = 45                  # scaled 7.5
RAW_SCORE_SECOND = 40                # scaled 6.7 (second candidate's pass)

SCALED_PROJECTED_PASS = 6.2
SCALED_AT_MARK = 6.5
SCALED_BELOW_MARK = 6.3
SCALED_HALF_UP = 5.5
SCALED_TRUNCATING = 5.3
SCALED_HIGH = 7.5

PASS_MARK_PROPOSED = 6.0
PASS_MARK_RATIFIED = 6.5
PASS_MARK_RATIFIED_HIGHER = 6.5      # ratified may differ from proposed

# ---------------------------------------------------------------------------
# Registration fees (PRD §3.3: late at/after deadline - 14 days; processing
# 1.5% of summed subtotal, round_half_up to whole cents, then added)
# ---------------------------------------------------------------------------
LATE_FEE_WINDOW_DAYS = 14
PROCESSING_RATE = 0.015
LATE_REFUND_RATIO = 0.5

WINDOW_BASE_FEE_CENTS = 30000
WINDOW_LATE_SURCHARGE_CENTS = 7500
WINDOW_CAPACITY_DEFAULT = 30
WINDOW_CAPACITY_TIGHT = 1

FEE_EARLY_CENTS = 30450              # 30000 + round_half_up(30000*0.015)=450
FEE_LATE_CENTS = 38063               # 37500 + round_half_up(37500*0.015)=563
FEE_PINNED_ROUNDING_BASE = 20160
FEE_PINNED_ROUNDING_SURCHARGE = 10160
FEE_PINNED_ROUNDING_CENTS = 30775    # 30320 + round_half_up(30320*0.015)=455
FEE_PINNED_ROUNDING_WRONG_ORDER = 30774  # per-component order (NOT used)
REFUND_HALF_OF_EARLY_CENTS = 15225   # round_half_up(30450 * 0.5)

# Standard window payload dates (PRD §3.3 ordering opens <= deadline <= start <= end)
STANDARD_SYLLABUS_CODE = "2026-A"
SECOND_SYLLABUS_CODE = "2026-B"
PRELIM_EXAM_CODE = "P"
PRELIM_EXAM_TITLE = "Probability"
PRELIM_EXAM_CREDIT_HOURS = 10
FM_EXAM_CODE = "FM"
FM_EXAM_TITLE = "Financial Mathematics"
P2_EXAM_CODE = "P2"
FM2_EXAM_CODE = "FM2"

STANDARD_WINDOW_CODE = "P-2026-10"
WINDOW_REGISTRATION_OPENS = "2026-09-01T00:00:00Z"
WINDOW_REGISTRATION_DEADLINE = "2026-10-01T00:00:00Z"
WINDOW_TESTING_STARTS = "2026-10-10T09:00:00Z"
WINDOW_TESTING_ENDS = "2026-10-12T17:00:00Z"
# Late tier begins at deadline minus LATE_FEE_WINDOW_DAYS.
LATE_TIER_STARTS = "2026-09-17T00:00:00Z"

# Second-edition FM2 window (2026-11 sitting) for transition-credit tests.
FM2_WINDOW_CODE = "FM2-2026-11"
FM2_REGISTRATION_OPENS = "2026-11-01T00:00:00Z"
FM2_REGISTRATION_DEADLINE = "2026-12-01T00:00:00Z"
FM2_TESTING_STARTS = "2026-12-10T09:00:00Z"
FM2_TESTING_ENDS = "2026-12-12T17:00:00Z"

# 2027 sitting of exam P (used by the proration fixtures).
WINDOW_2027_CODE = "P-2027-06"
WINDOW_2027_OPENS = "2027-05-01T00:00:00Z"
WINDOW_2027_DEADLINE = "2027-06-01T00:00:00Z"
WINDOW_2027_TESTING_STARTS = "2027-06-10T09:00:00Z"
WINDOW_2027_TESTING_ENDS = "2027-06-12T17:00:00Z"

# ---------------------------------------------------------------------------
# VEE (PRD §3.4: grade floor 2.7, >= boundary approves; 0.0..4.0 range)
# ---------------------------------------------------------------------------
VEE_GRADE_MIN = 2.7
VEE_GRADE_PASS = 3.3
VEE_GRADE_BOUNDARY = 2.7
VEE_GRADE_BELOW = 2.6
VEE_GRADE_REJECT_FIRST = 2.5
VEE_GRADE_RESUBMIT = 3.1
VEE_GRADE_HIGH = 3.9
VEE_GRADE_OUT_OF_RANGE = 5.0
VEE_UNIVERSITY = "State University"
VEE_UNIVERSITY_OTHER = "Other University"
VEE_TOPICS = ("ECONOMICS", "CORPORATE_FINANCE", "APPLIED_STATISTICS")
VEE_COURSE_TITLES = {
    "ECONOMICS": "EC101",
    "CORPORATE_FINANCE": "FN201",
    "APPLIED_STATISTICS": "ST301",
}

# ---------------------------------------------------------------------------
# Tracks, modules, completion weights (PRD §3.5)
# ---------------------------------------------------------------------------
DEFAULT_COOLDOWN_DAYS = 14
NONCAPSTONE_WEIGHT = 2
CAPSTONE_WEIGHT = 3
PROJECT_WEIGHT = 2

TRACK_QFI = "QFI"
TRACK_ILA = "ILA"
MODULE_M1_CODE = "QFI-M1"
MODULE_M1_TITLE = "QF Module 1"
MODULE_M2_CODE = "QFI-M2"
MODULE_M2_TITLE = "QF Module 2"
MODULE_CAP_CODE = "QFI-CAP"
MODULE_CAP_TITLE = "QF Capstone"
MODULE_PASSING_SCORE = 70
CAPSTONE_PASSING_SCORE = 75
SUBMIT_SCORE_PASS = 80
SUBMIT_SCORE_FAIL = 10

# completion_pct milestones with 2 non-capstone modules + capstone + project
# (round_half_up(100 * weighted / 9, 2) at each phase)
PCT_AFTER_ONE_MODULE = 22.22
PCT_AFTER_ALL_NONCAPSTONE = 44.44
PCT_AFTER_PROJECT = 66.67
PCT_COMPLETED = 100.0

# ---------------------------------------------------------------------------
# Project assessment grading (PRD §3.6: tolerance 10; pass at >= 70)
# ---------------------------------------------------------------------------
CONSENSUS_TOLERANCE = 10
PROJECT_PASS_SCORE = 70
GRADER_1_ID = "grader-001"
GRADER_2_ID = "grader-002"
GRADER_3_ID = "grader-003"
GRADER_4_ID = "grader-004"
PROJECT_SCORE_G1 = 80
PROJECT_SCORE_G2 = 74
PROJECT_FINAL_CONSENSUS = 77         # round_half_up((80+74)/2)
PROJECT_SPLIT_G1 = 85
PROJECT_SPLIT_G2 = 60                # |85-60| = 25 > 10 -> SPLIT
PROJECT_SPLIT_RESOLVER = 72
PROJECT_FINAL_MEDIAN = 72            # median(85, 60, 72)
PROJECT_TITLE = "QF Case Study"

# ---------------------------------------------------------------------------
# Professionalism course sessions (PRD §3.7)
# ---------------------------------------------------------------------------
SESSION_CODE = "APC-1"
SESSION_STARTS = "2026-11-05T09:00:00Z"
SESSION_ENDS = "2026-11-05T17:00:00Z"
SESSION_CODE_SAME_DAY = "APC-2"
SESSION_SAME_DAY_STARTS = "2026-11-05T15:00:00Z"
SESSION_SAME_DAY_ENDS = "2026-11-05T16:00:00Z"
SESSION_CODE_NEXT_DAY = "APC-3"
SESSION_NEXT_DAY_STARTS = "2026-11-06T09:00:00Z"
SESSION_NEXT_DAY_ENDS = "2026-11-06T10:00:00Z"
SESSION_CODE_PAST = "APC-0"
SESSION_PAST_STARTS = "2026-09-10T09:00:00Z"
SESSION_PAST_ENDS = "2026-09-10T17:00:00Z"
SESSION_CAPACITY_DEFAULT = 30

# ---------------------------------------------------------------------------
# Transfer credit (PRD §3.8: bilateral cap 30; non-bilateral half, cap 15)
# ---------------------------------------------------------------------------
BILATERAL_CAP = 30
NON_BILATERAL_CAP = 15
NON_BILATERAL_RATIO = 0.5
TRANSFER_IFOA_CLAIM = 40
TRANSFER_IFOA_GRANTED = 30
TRANSFER_CIA_CLAIM = 25
TRANSFER_CIA_GRANTED = 25
TRANSFER_CAS_CLAIM = 40
TRANSFER_CAS_GRANTED = 15
TRANSFER_IAA_CLAIM = 20
TRANSFER_IAA_GRANTED = 10
TRANSFER_OTHER_CLAIM = 50
TRANSFER_OTHER_GRANTED = 0
TRANSFER_TOTAL_ALL_TIERS = 80        # 30 + 25 + 15 + 10

# ---------------------------------------------------------------------------
# CPD (PRD §3.8: base 30 h; carryover cap 10; admission-year proration
# months_remaining = 13 - admission_month, rounded up)
# ---------------------------------------------------------------------------
CPD_BASE_HOURS = 30
CPD_CARRYOVER_CAP = 10
CPD_CYCLE_YEAR = 2027
CPD_CYCLE_YEAR_NEXT = 2028
CPD_REQUIRED_FULL_YEAR_CAPPED_CARRYOVER = 20   # 30 - min(12, 10)
CPD_REQUIRED_FULL_YEAR_NO_CARRYOVER = 30       # 30 - 0
CPD_REQUIRED_JULY_ADMISSION = 12               # ceil(30*6/12) - min(3, 10)
CPD_ATTESTED_COMPLIANT = 32
CPD_ATTESTED_HIGH = 40
CPD_ATTESTED_LOW = 5
CPD_ATTESTED_EXACT = 30
CPD_ATTESTED_SECOND = 12
CPD_CARRYOVER_OVER_CAP = 12
CPD_CARRYOVER_SMALL = 3
CPD_VERIFY_SHORTFALL = 18
CPD_VERIFY_EXACT = 30
CPD_VERIFY_OVER = 35

# ---------------------------------------------------------------------------
# Credential evaluation (PRD §3.9: canonical deficiency order)
# ---------------------------------------------------------------------------
ASA_MIN_TOTAL_CREDITS = 10
ASA_TRANSFER_CREDIT_CAP = 15
DEFICIENCIES_ASA_BARE = [
    "MISSING_PRELIM_CREDIT",
    "MISSING_VEE_TOPIC",
    "INSUFFICIENT_TOTAL_CREDITS",
]
DEFICIENCIES_FSA_NO_ASA = [
    "MISSING_ASA",
    "TRACK_INCOMPLETE",
    "MISSING_PROJECT_PASS",
    "MISSING_PROFESSIONALISM",
]

# ---------------------------------------------------------------------------
# Discipline (PRD §3.9)
# ---------------------------------------------------------------------------
SUSPENSION_DAYS = 30
SUSPENDED_UNTIL_FROM_0905 = "2026-10-05T00:00:00Z"
SEVERITY_MINOR = 2
SEVERITY_LOW = 4
SEVERITY_MID = 5
SEVERITY_HIGH = 7
SEVERITY_MAX = 10

# ---------------------------------------------------------------------------
# Candidate identities used across recipes
# ---------------------------------------------------------------------------
CANDIDATE1_EMAIL = "cand1@example.com"
CANDIDATE2_EMAIL = "cand2@example.com"
CANDIDATE_A_EMAIL = "candA@example.com"
CANDIDATE_B_EMAIL = "candB@example.com"
CANDIDATE_C_EMAIL = "candC@example.com"
