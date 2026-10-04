"""Domain thresholds and pinned literals — numeric constants from the PRD.

Every value below is stated verbatim in the PRD (calculation constants,
temporal windows, the logical-clock start, and the pinned fixture
datetimes used throughout the suite).
"""

# --- Score integrity thresholds (PRD §3.5) ---
GAIN_THRESHOLD = 30
SIMILARITY_THRESHOLD = 0.85
MIN_MATCHED_ITEMS = 20

# --- Provisional scaling weights (PRD §3.5) ---
SECTION_WEIGHT_0 = 1.2
SECTION_WEIGHT_1 = 0.8
SECTION_WEIGHT_2 = 1.0
EQUATE_FACTOR = 0.5

# --- Audit compliance scoring (PRD §3.1) ---
PASS_THRESHOLD = 80
FACILITY_WEIGHT = 5
STAFFING_WEIGHT = 7
EQUIPMENT_WEIGHT = 3
UNANNOUNCED_MULTIPLIER = 1.5

# --- Temporal rules (PRD §3.2, §3.4, §3.6) ---
TURNAROUND_BUFFER_MIN = 60
LATE_ARRIVAL_MINUTES = 15
RESPONSE_WINDOW_DAYS = 30

# --- Logical clock (PRD §2.5) ---
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Pinned fixture datetimes ---
TEST_DATE = "2026-10-10"
TEST_DATE_FAR = "2026-12-12"
SESSION_START_TIME = "08:00"
SESSION_END_TIME = "12:00"
CLOCK_TEST_DAY_MORNING = "2026-10-10T07:45:00Z"
CLOCK_TEST_DAY_AFTER = "2026-10-10T12:30:00Z"
CLOCK_PAST_RESPONSE_DEADLINE = "2026-11-10T00:00:00Z"
# Notify at CLOCK_TEST_DAY_AFTER plus RESPONSE_WINDOW_DAYS days.
EXPECTED_RESPONSE_DEADLINE_ISO = "2026-11-09T12:30:00Z"
AUDIT_SCHEDULED_DATE = "2026-09-05"

# --- Identity-document fixtures (expiry strictly after any check-in date) ---
DOC_EXPIRY_VALID = "2027-06-01"
DOC_EXPIRY_VALID_LATE = "2028-01-01"
DEFAULT_DATE_OF_BIRTH = "2000-01-15"

# --- Score-entry fixtures ---
DEFAULT_TOTAL_SCORED_ITEMS = 40
RAWS_PROVISIONAL_97 = [33, 21, 40]
RAWS_PROVISIONAL_120 = [40, 40, 40]

# --- Audit finding fixtures ---
# (1,1,2,0) ANNOUNCED -> base deduction 18 -> compliance_score 82 -> PASSED.
PASSING_AUDIT_FINDINGS = {
    "facility_findings": 1,
    "staffing_findings": 1,
    "equipment_findings": 2,
    "high_severity_findings": 0,
}
PASSING_AUDIT_SCORE = 82
# (2,1,3,0) UNANNOUNCED -> base 26 -> round_half_up(1.5*26)=39 -> score 61 -> FAILED.
CASCADE_AUDIT_FINDINGS = {
    "facility_findings": 2,
    "staffing_findings": 1,
    "equipment_findings": 3,
    "high_severity_findings": 0,
}
CASCADE_AUDIT_SCORE = 61

# --- Named opaque operator ids (segregation-of-duties fixtures) ---
ANALYST_1_ID = "analyst-1"
ADMIN_1_ID = "admin-1"
ADMIN_2_ID = "admin-2"
