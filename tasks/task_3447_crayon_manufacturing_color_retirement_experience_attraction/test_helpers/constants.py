"""Domain thresholds and constants, transcribed from the PRD's own prose.

Every value below is stated verbatim in PRD.md (section noted per constant).
"""

# --- Logical clock (PRD section 2.4) ---------------------------------------
CLOCK_BOOT_DEFAULT = "2026-09-01T00:00:00Z"  # "startup default is exactly 2026-09-01T00:00:00Z"

# --- Vote tally (PRD section 3.1, vote_tally) -------------------------------
MIN_TURNOUT = 10
INTRO_THRESHOLD = 0.55
RETIRE_THRESHOLD = 0.60
VOTE_WEIGHTS_INTRODUCTION = {"KIDS": 1.0, "PARENTS": 1.5, "EDUCATORS": 2.0, "COLLECTORS": 1.2}
VOTE_WEIGHTS_RETIREMENT = {"KIDS": 1.0, "PARENTS": 1.0, "EDUCATORS": 1.5, "COLLECTORS": 2.5}

# --- Season window and lead time (PRD section 2.10) -------------------------
SEASON_START = "2027-06-01T00:00:00Z"
SEASON_END = "2027-08-31T23:59:59Z"
PRODUCTION_LEAD_DAYS = 60
ARCHIVE_AFTER_DAYS = 30  # archive_after_date = retired_on + thirty days (PRD 3.1)

# --- Ticket dynamic pricing (PRD section 3.7, ticket_dynamic_price) ---------
LOW_TIER_CEIL = 0.5
HIGH_TIER_FLOOR = 0.8
LOW_MULT = 0.9
HIGH_MULT = 1.25
GROUP20_MULT = 0.85
GROUP50_MULT = 0.75
WEEKEND_MULT = 1.15
CHARTER_GROUP_MULT = 0.80

# --- Ticket structural bounds (PRD section 3.7) -----------------------------
GROUP_SIZE_MIN = 10
GROUP_SIZE_MAX = 100
START_MINUTE_MAX = 1339
DURATION_MINUTES_MIN = 30
SESSION_TURNOVER_BUFFER_MINUTES = 30

# --- Packing penalty (PRD sections 2.6 / 3.4, packing_penalty) --------------
UNDER_UNIT_PENALTY_CENTS = 18.75
OVER_FACTOR = 1.5
TOLERANCE_UNITS = 5

# --- Assortment spec (PRD section 3.4) --------------------------------------
ALLOWED_BOX_SIZES = {8, 16, 24, 64}

# --- Recall severity (PRD section 3.2, recall_severity_classification) ------
CLASS_II_FLOOR = 1000
CLASS_I_FLOOR = 10000
COOLING_III_DAYS = 7
COOLING_II_DAYS = 14
COOLING_I_DAYS = 30

# --- Licensed lines (PRD section 3.6) ---------------------------------------
ROYALTY_RATE_MAX = 0.5

# --- Pagination defaults (PRD section 2.3) ----------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
