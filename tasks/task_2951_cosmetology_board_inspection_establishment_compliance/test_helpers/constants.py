"""Numeric and temporal constants pinned by the PRD.

Every value here is copied from a specific PRD sentence so that a test can
assert against the specification rather than against a magic number.
"""

# --- Logical clock (PRD 2.4) -------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00.000Z"
CLOCK_START_DATE = "2026-08-01"

# --- Pagination (PRD 2.3) ----------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Severity weights used by inspection scoring (PRD 3.5) -------------------
SEVERITY_WEIGHTS = {
    "MINOR": 1.0,
    "MAJOR": 2.5,
    "CRITICAL": 5.0,
    "IMMINENT_HAZARD": 8.0,
}

# --- Severity total order (PRD 3.7 max_finding_severity) ---------------------
SEVERITY_ORDER = ["MINOR", "MAJOR", "CRITICAL", "IMMINENT_HAZARD"]

# --- On-site-correction credit, the only input that differs between the two
#     scoring variants besides the cutoff instant (PRD 3.5) -------------------
PROVISIONAL_ON_SITE_CREDIT = 0.50
FINAL_ON_SITE_CREDIT = 0.25

# --- Repeat lookback and factors (PRD 3.5) -----------------------------------
REPEAT_LOOKBACK_DAYS = 730
REPEAT_FACTOR_NONE = 1.0
REPEAT_FACTOR_ONE = 1.5
REPEAT_FACTOR_MANY = 2.0

# --- Outcome bands (PRD 3.5) -------------------------------------------------
OUTCOME_FAIL_SCORE_THRESHOLD = 40.00
OUTCOME_CONDITIONAL_PASS_SCORE_THRESHOLD = 10.00

# --- Establishment posture thresholds (PRD 2.6) ------------------------------
POSTURE_FROZEN_DEMERITS = 100.00
POSTURE_RESTRICTED_DEMERITS = 50.00
POSTURE_WATCH_DEMERITS = 20.00

# --- Licence status transitions driven by demerits (PRD 3.7 hop four) --------
REVOKE_DEMERIT_THRESHOLD = 200.00
PROBATION_DEMERIT_THRESHOLD = 100.00

# --- Operable / non-operable establishment statuses (PRD 2.6) ----------------
OPERABLE_ESTABLISHMENT_STATUSES = ["PENDING_INSPECTION", "ACTIVE", "PROBATION"]
NON_OPERABLE_ESTABLISHMENT_STATUSES = [
    "SUSPENDED",
    "CLOSED_IMMINENT_HAZARD",
    "REVOKED",
]

# --- Citation fine computation (PRD 3.7) -------------------------------------
SURCHARGE_TOLERANCE_POINTS = 30.00
SURCHARGE_CENTS_PER_POINT = 400
DEMERIT_TIER_MULTIPLIERS = [
    (0.00, 1.00),
    (20.00, 1.25),
    (50.00, 1.60),
    (200.00, 2.00),
]
SUBJECT_FACTOR_ESTABLISHMENT = 1.00
SUBJECT_FACTOR_PRACTITIONER = 0.50
FINE_FLOOR_CENTS = 5000
FINE_CEILING_CENTS = 250000
FEE_TIER_LOW_MAX_CENTS = 25000
FEE_TIER_MID_MAX_CENTS = 100000
FEE_RATE_LOW = 0.05
FEE_RATE_MID = 0.08
FEE_RATE_HIGH = 0.12

# --- Citation deadlines (PRD 3.7) --------------------------------------------
DUE_AT_OFFSET_DAYS = 30
CONTEST_DEADLINE_OFFSET_DAYS = 20

# --- Hearings (PRD 3.8) ------------------------------------------------------
MAX_HEARING_ROUNDS = 2
AMENDED_FINE_FLOOR_CENTS = 5000

# --- Delinquency sweep (PRD 3.9) --------------------------------------------
LATE_PENALTY_RATE = 0.10

# --- Sanitation protocol minimum contact times in minutes (PRD 3.4) ---------
CONTACT_MINUTES_MINIMUMS = {
    "IMPLEMENT_DISINFECTION": 10,
    "FOOT_SPA_AFTER_CLIENT": 10,
    "FOOT_SPA_END_OF_DAY": 10,
    "FOOT_SPA_WEEKLY_BIOFILM": 360,
}
FOOT_SPA_CYCLE_GAP_MINUTES = 5
FOOT_SPA_STATION_LOG_TYPES = [
    "FOOT_SPA_AFTER_CLIENT",
    "FOOT_SPA_END_OF_DAY",
    "FOOT_SPA_WEEKLY_BIOFILM",
]
IMPLEMENT_STATION_TYPES = ["STYLING_CHAIR", "NAIL_TABLE", "FACIAL_ROOM"]
BIOFILM_CURRENCY_WINDOW_DAYS = 7

# --- School / apprentice hour ledgers (PRD 3.2) -----------------------------
SCHOOL_DAILY_HOUR_CAP = 8
APPRENTICE_WEEKLY_HOUR_CAP = 40
APPRENTICE_CREDIT_RATIO = 0.60
NON_APPRENTICE_TRACK_DAILY_CAP = 8
NON_APPRENTICE_TRACK_RATIO = 1.00
STANDALONE_APPRENTICESHIP_REQUIRED_HOURS = 1600.00
MAX_TRAINING_RECORD_HOURS = 24

# --- Licensing (PRD 3.2) -----------------------------------------------------
LICENSE_TERM_DAYS = 730

# --- Inspection window geometry (PRD 3.5) -----------------------------------
INSPECTION_COOLDOWN_HOURS = 24
NON_TERMINAL_INSPECTION_STATUSES = ["SCHEDULED", "IN_PROGRESS", "PENDING_REVIEW"]
REINSPECTION_PARENT_OUTCOMES = ["CONDITIONAL_PASS", "FAIL", "IMMEDIATE_CLOSURE"]
HAZARD_CLEARANCE_MAX_SCORE = 10.00

# --- Infection incidents (PRD 3.9) ------------------------------------------
NOTIFICATION_WINDOW_HOURS_MULTI_CASE = 24
NOTIFICATION_WINDOW_HOURS_SINGLE_CASE = 72
MULTI_CASE_THRESHOLD = 2
INFECTION_SANCTION_POINTS = 10.00
AUTO_SUSPEND_SANCTION_THRESHOLD = 15.00

# --- Ledger (PRD 2.5) -------------------------------------------------------
LEDGER_TYPES = ["FINE_CENTS", "DEMERIT_POINTS", "SANCTION_POINTS"]
ENTRY_REASONS = [
    "CITATION_ASSESSMENT",
    "CITATION_PAYMENT",
    "CITATION_LATE_PENALTY",
    "CITATION_AMENDMENT_ADJUSTMENT",
    "CITATION_DISMISSAL_REVERSAL",
    "INSPECTION_DEMERIT_ASSESSMENT",
    "INSPECTION_DEMERIT_REVERSAL",
    "INFECTION_SANCTION_ASSESSMENT",
    "REINSTATEMENT_SANCTION_REVERSAL",
]

# --- Roles (PRD 2.1) --------------------------------------------------------
ALL_ROLES = [
    "BoardAdmin",
    "Inspector",
    "HearingOfficer",
    "EstablishmentOwner",
    "Practitioner",
    "SchoolRegistrar",
    "HealthAuthorityLiaison",
]
ENTITY_BACKED_ROLES = ["EstablishmentOwner", "Practitioner", "SchoolRegistrar"]
OPAQUE_ROLES = ["BoardAdmin", "Inspector", "HearingOfficer", "HealthAuthorityLiaison"]

# --- Practitioner statuses that refuse a posting or activation (PRD 3.2) ----
NON_POSTABLE_PRACTITIONER_STATUSES = [
    "STUDENT",
    "EXAM_ELIGIBLE",
    "PROBATION",
    "SUSPENDED",
    "LAPSED",
    "REVOKED",
]

# --- Immutable record types: no updated_at, no version (PRD 2.4) ------------
IMMUTABLE_ENTITIES = ["TrainingRecord", "ViolationCode", "SanitationLog", "LedgerEntry"]
