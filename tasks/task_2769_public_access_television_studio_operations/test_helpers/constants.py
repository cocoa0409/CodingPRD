"""Domain thresholds and reference data drawn from the PRD's stated rules.

Every value below is quoted or derived from a numeric rule the PRD states in
prose (certification pass mark, suspension arithmetic, deposit rates, franchise
reserve tiers, community-impact norms, retention months).
"""

# --- Curriculum and certification (PRD 3.1) -------------------------------
PASS_SCORE_MIN = 80

# --- Damage penalties and suspension (PRD 3.7) ---------------------------
SUSPENSION_THRESHOLD_POINTS = 3
SUSPENSION_POINTS_BY_SEVERITY = {
    "MINOR": 1,
    "MAJOR": 2,
    "TOTAL_LOSS": 3,
}
REPAIR_ESCALATION_CENTS = 50_000

# --- Program review (PRD 3.3) -------------------------------------------
MAX_REVISION_ROUNDS = 2
CURRENT_STATEMENT_VERSION = "2026.1"
SUPERSEDED_STATEMENT_VERSION = "2025.2"
REQUIRED_ATTESTATION_KINDS = ["INDEMNIFICATION", "COPYRIGHT_CLEARANCE", "CONTENT_POLICY"]
INDEMNIFICATION_TERM_DAYS = 365
UNPROTECTED_FINDING_CATEGORIES = [
    "OBSCENITY",
    "DEFAMATION",
    "TRUE_THREAT",
    "INCITEMENT_TO_IMMINENT_LAWLESS_ACTION",
    "CHILD_EXPLOITATION",
    "COMMERCIAL_ADVERTISING",
    "COPYRIGHT_INFRINGEMENT",
    "TECHNICAL_STANDARDS_FAILURE",
]

# --- Deposits, fees and reservation arithmetic (PRD 3.6, 3.7) -----------
RISK_BP_PER_SUSPENSION_POINT = 1500
RISK_BP_CAP = 4500
HOURLY_DEPOSIT_RATE_BP = 500
LIVE_LINK_SURCHARGE_BP = 2000
LATE_FEE_BP_PER_HOUR = 750
CHECKOUT_LEAD_SECONDS = 3600
DEPOSIT_HOLD_CAP_CENTS = 500_000

# --- Franchise fee allocation (PRD 3.8) ---------------------------------
ADMIN_RESERVE_BP_BASE = 800
ADMIN_RESERVE_BP_HIGH = 500
HIGH_TIER_THRESHOLD_CENTS = 5_000_000
CAPITAL_RATE_BP = 3500

# --- Community impact index (PRD 3.9) -----------------------------------
WEIGHT_REACH = 0.5
WEIGHT_DEMAND = 0.3
WEIGHT_VOLUNTEER = 0.2
HOUSEHOLD_NORM = 1000
VIEW_NORM = 500
VOLUNTEER_TENTHS_NORM = 100
SECONDS_PER_TENTH_HOUR = 360
RETENTION_MONTHS = {"STANDARD_24M": 24, "EXTENDED_60M": 60, "PERMANENT": None}

# --- Series hold plans (PRD 3.2) ----------------------------------------
SERIES_LAPSE_MISSED_WINDOWS = 2

# --- Crew staffing (PRD 3.5) --------------------------------------------
LIVE_ROLES_REQUIRING_LIVE_CERT = ["DIRECTOR", "SWITCHER"]

# --- Logical clock (PRD 2.5) --------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Reference instants used by the composite setups below. They are chosen so a
# BASIC training session (2026-08-05 17:00-21:00Z) has ended, indemnification
# signed at that point is still in force, and airdates sit comfortably later.
CLOCK_AFTER_BASIC_SESSION = "2026-08-06T00:00:00Z"
CLOCK_AFTER_ADVANCED_SESSION = "2026-08-08T00:00:00Z"
CLOCK_AFTER_LIVE_SESSION = "2026-08-10T00:00:00Z"

# --- Reference test data ------------------------------------------------
TEST_DEFAULTS = {
    "CHANNEL_WINDOW_START_MINUTE": 1080,   # 18:00 UTC
    "CHANNEL_WINDOW_END_MINUTE": 1380,     # 23:00 UTC
    "CHANNEL_BUFFER_SECONDS": 120,
    "PROGRAM_RUNTIME_SECONDS": 1800,
    "SLOT_OCCUPIED_SECONDS": 1920,         # runtime 1800 + buffer 120
    "BASE_DEPOSIT_CENTS": 12_345,
    "REPLACEMENT_VALUE_CENTS": 900_000,
    "TWO_HOUR_HOLD_CENTS": 12_962,         # base 12345 + duration line 617
    "SEAT_CAPACITY": 12,
}

BASIC_COMPETENCY_CODES = ["STUDIO_FLOOR", "EDIT_SUITE"]
ADVANCED_COMPETENCY_CODES = ["AUDIO_BOARD"]
LIVE_COMPETENCY_CODES = ["LIVE_SWITCHER"]
