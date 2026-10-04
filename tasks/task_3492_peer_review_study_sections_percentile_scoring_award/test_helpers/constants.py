"""Domain thresholds and pinned literals.

Every value in this module is pinned by a verbatim PRD sentence; the PRD
quote is carried in a comment next to the constant. Values that the PRD
does not pin (names, pa_numbers, concrete scenario dates) live in
factories.py as overridable defaults instead.
"""

# --- Logical clock ---------------------------------------------------------
# PRD: "Before any clock operation is performed, the logical clock starts at
# exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time
# thereafter."
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Scoring ---------------------------------------------------------------
# PRD: "An application with fewer than two submitted critiques becomes
# UNSCORED (a terminal state)"
MIN_CRITIQUES_TO_SCORE = 2

# PRD: "an application must hold at least two live assignments to remain
# under review"
MIN_LIVE_ASSIGNMENTS = 2

# PRD: "a weight of two for a PRIMARY assignment, one for a SECONDARY
# assignment"
PRIMARY_WEIGHT = 2
SECONDARY_WEIGHT = 1

# PRD: "The application's impact_score is that weighted mean multiplied by
# ten and rounded half up to a whole number, yielding an integer from 10 to
# 90."
IMPACT_SCORE_MULTIPLIER = 10
IMPACT_SCORE_MIN = 10
IMPACT_SCORE_MAX = 90

# PRD: "The critique supplies six integer scores, each from 1 to 9"
CRITERION_SCORE_MIN = 1
CRITERION_SCORE_MAX = 9

# PRD: "Percentile values are rendered with exactly one decimal place, and
# criterion means with exactly two decimal places, both rounded half up."
PERCENTILE_DECIMALS = 1
CRITERION_MEAN_DECIMALS = 2

# --- Payline / select pay --------------------------------------------------
# PRD: "Each candidate's effective percentile is its percentile_normalized
# reduced by an early-stage bonus — five percentile points when the
# applicant's career_stage is EARLY_STAGE_INVESTIGATOR, zero otherwise"
ESI_PAYLINE_BONUS = 5.0

# PRD: "but never below one-tenth of a percentile point"
EFFECTIVE_PERCENTILE_FLOOR = 0.1

# --- JIT -------------------------------------------------------------------
# PRD: "a just-in-time request is automatically created for it in ISSUED
# status with its due_date thirty days after the current logical clock"
JIT_RESPONSE_WINDOW_DAYS = 30

# PRD: "records the supplied budget_cut_pct (defaulting to zero, and never
# above 0.30 — a value outside that range is rejected with ERR_VALIDATION)"
BUDGET_CUT_MAX_PCT = 0.30
BUDGET_CUT_DEFAULT_PCT = 0

# PRD: "Its required_items are derived from the application's flags:
# OTHER_SUPPORT and BUDGET_JUSTIFICATION always, plus IRB_APPROVAL exactly
# when human_subjects_involved is set, plus IACUC_APPROVAL exactly when
# vertebrate_animals_involved is set."
JIT_ITEM_OTHER_SUPPORT = "OTHER_SUPPORT"
JIT_ITEM_BUDGET_JUSTIFICATION = "BUDGET_JUSTIFICATION"
JIT_ITEM_IRB_APPROVAL = "IRB_APPROVAL"
JIT_ITEM_IACUC_APPROVAL = "IACUC_APPROVAL"
JIT_BASE_ITEMS = [JIT_ITEM_OTHER_SUPPORT, JIT_ITEM_BUDGET_JUSTIFICATION]

# --- Award -----------------------------------------------------------------
# PRD: "its end_date falls exactly requested_years times 365 days after the
# start_date"
AWARD_PERIOD_DAYS = 365

# PRD: "Its terms_and_conditions always contain STANDARD_TERMS_V1, and gain
# RESTRICTED_DRAW_DOWN exactly when the accepted budget_cut_pct is greater
# than zero."
# PRD: "terms_and_conditions gaining TRANSFERRED_AWARD alongside
# STANDARD_TERMS_V1"
TERM_STANDARD = "STANDARD_TERMS_V1"
TERM_RESTRICTED_DRAW_DOWN = "RESTRICTED_DRAW_DOWN"
TERM_TRANSFERRED_AWARD = "TRANSFERRED_AWARD"

# --- Post-award administration ---------------------------------------------
# PRD: "the filing window closes ninety days after the current period's end"
REPORT_GRACE_DAYS = 90

# PRD: "the requested extension must not exceed 365 days beyond the current
# end_date (ERR_NCE_LIMIT_EXCEEDED)"
NCE_MAX_EXTENSION_DAYS = 365

# PRD: "When the amount is at most one quarter of the unobligated balance —
# the quarter computed with half-up rounding to a whole cent — the
# modification lands directly in the terminal AUTO_APPROVED state"
CARRYOVER_AUTO_APPROVE_PCT = 0.25

# --- Review assignment gates ------------------------------------------------
# PRD: "A reviewer may hold at most four active assignments"
MAX_ACTIVE_ASSIGNMENTS_PER_REVIEWER = 4

# PRD: "an application may hold at most three live assignments"
MAX_LIVE_ASSIGNMENTS_PER_APPLICATION = 3

# PRD: "if the absolute difference between the two sections' meeting_date
# values is within seven days — inclusive, so exactly seven days apart is a
# conflict while seven days and one second is not — creation is rejected
# with ERR_MEETING_PROXIMITY_CONFLICT"
MEETING_PROXIMITY_BUFFER_DAYS = 7

# --- Application intake -----------------------------------------------------
# PRD: "the requested_years project period (one to five years)"
MIN_PROJECT_YEARS = 1
MAX_PROJECT_YEARS = 5

# PRD: "A priority_alignment_score from 1 to 5 captures program-priority
# alignment and is required exactly when the recommendation is FUND"
PRIORITY_ALIGNMENT_MIN = 1
PRIORITY_ALIGNMENT_MAX = 5

# --- Pagination -------------------------------------------------------------
# PRD: "The limit parameter specifies the maximum number of items to return;
# it defaults to 10, with a minimum of 1 and a maximum of 100. The offset
# parameter specifies the number of items to skip; it defaults to 0 and may
# not be negative."
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
