"""All PRD/scaffold-pinned constants. Exactly one definition site per symbol."""

# --- Logical clock -----------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"  # PRD §2.4 startup default

# --- Scoring / percentile constants (scaffold calculations.impact_score) -----
MIN_CRITIQUES_TO_SCORE = 2
MIN_LIVE_ASSIGNMENTS = 2
PRIMARY_WEIGHT = 2
SECONDARY_WEIGHT = 1
PERCENTILE_DECIMALS = 1
CRITERION_MEAN_DECIMALS = 2

# --- Award budget build (calculations.award_budget_build) --------------------
BUDGET_CUT_MAX_PCT = 0.30
AWARD_PERIOD_DAYS = 365

# --- Payline determination (calculations.payline_determination) --------------
ESI_PAYLINE_BONUS = 5.0
MIN_EFFECTIVE_PERCENTILE = 0.1
JIT_RESPONSE_WINDOW_DAYS = 30

# --- Carryover (calculations.carryover_auto_approval) ------------------------
CARRYOVER_AUTO_APPROVE_PCT = 0.25

# --- Assignment gates ---------------------------------------------------------
MAX_ACTIVE_ASSIGNMENTS_PER_REVIEWER = 4
MEETING_PROXIMITY_BUFFER_DAYS = 7
MAX_LIVE_ASSIGNMENTS_PER_APPLICATION = 3

# --- Progress reports / NCE ---------------------------------------------------
REPORT_WINDOW_GRACE_DAYS = 90
NCE_MAX_EXTENSION_DAYS = 365

# --- Roles (scaffold §1.7) ----------------------------------------------------
ROLE_PROGRAM_OFFICER = "ProgramOfficer"
ROLE_REFERRAL_OFFICER = "ReferralOfficer"
ROLE_SRO = "ScientificReviewOfficer"
ROLE_REVIEWER = "Reviewer"
ROLE_COUNCIL_MEMBER = "CouncilMember"
ROLE_GRANTS_OFFICER = "GrantsOfficer"
ROLE_APPLICANT = "Applicant"
ALL_ROLES = (
    ROLE_PROGRAM_OFFICER,
    ROLE_REFERRAL_OFFICER,
    ROLE_SRO,
    ROLE_REVIEWER,
    ROLE_COUNCIL_MEMBER,
    ROLE_GRANTS_OFFICER,
    ROLE_APPLICANT,
)

# --- Enums --------------------------------------------------------------------
ACTIVITY_CODES = ("R01", "R21", "R03")
CAREER_STAGES = (
    "NEW_INVESTIGATOR",
    "EARLY_STAGE_INVESTIGATOR",
    "ESTABLISHED_INVESTIGATOR",
)
CAREER_STAGE_ESI = "EARLY_STAGE_INVESTIGATOR"
ASSIGNMENT_ROLES = ("PRIMARY", "SECONDARY")
RECOMMENDATIONS = ("FUND", "DEFER", "NOT_FUND")
RECRUIT_DECISIONS = ("ACCEPT", "DECLINE")
ADJUDICATE_DECISIONS = ("APPROVE", "DENY")
JIT_DECISIONS = ("ACCEPT", "RETURN")
TRANSFER_DECISIONS = ("ACCEPT", "DECLINE")
MODIFICATION_TYPES = ("CARRYOVER", "NO_COST_EXTENSION", "TERMINATION")

# --- JIT required item names (scaffold JitRequest.required_items) -------------
JIT_ITEM_OTHER_SUPPORT = "OTHER_SUPPORT"
JIT_ITEM_BUDGET_JUSTIFICATION = "BUDGET_JUSTIFICATION"
JIT_ITEM_IRB = "IRB_APPROVAL"
JIT_ITEM_IACUC = "IACUC_APPROVAL"

# --- Award terms and conditions (scaffold Award.terms_and_conditions) ---------
TERM_STANDARD = "STANDARD_TERMS_V1"
TERM_RESTRICTED_DRAW_DOWN = "RESTRICTED_DRAW_DOWN"
TERM_TRANSFERRED_AWARD = "TRANSFERRED_AWARD"

# --- Status groupings ----------------------------------------------------------
TERMINAL_APPLICATION_STATUSES = ("AWARDED", "NOT_FUNDED", "UNSCORED", "WITHDRAWN")
LIVE_ASSIGNMENT_STATUSES = ("ASSIGNED", "ACCEPTED", "CRITIQUE_SUBMITTED")
ACTIVE_ASSIGNMENT_STATUSES = ("ASSIGNED", "ACCEPTED")
WITHDRAWABLE_APPLICATION_STATUSES = ("DRAFT", "SUBMITTED", "REFERRED", "UNDER_REVIEW")
NON_TERMINAL_JIT_STATUSES = ("ISSUED", "SUBMITTED", "RETURNED")
NON_TERMINAL_TRANSFER_STATUSES = ("PROPOSED", "RELINQUISHED")

# --- Pagination (scaffold response_envelope.pagination_defaults) ---------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
