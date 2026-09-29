"""Domain thresholds and shared literals drawn from the PRD's calculations."""

# --- logical clock -------------------------------------------------------
# The clock reads this instant until it is set for the first time.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- diligence composite ------------------------------------------------
COMPOSITE_WEIGHTS = {
    "business_model_score": 0.20,
    "funding_score": 0.25,
    "compliance_capability_score": 0.35,
    "effective_complaint_history_score": 0.20,
}
TIER_FLOORS = {"TIER_1": 85.0, "TIER_2": 70.0, "TIER_3": 55.0}
COMPLIANCE_CAPABILITY_FLOOR = 60
COMPOSITE_PASS_FLOOR = 55.0
RENEWAL_BPS_PER_POINT = 5

# --- posture ladder -----------------------------------------------------
FREEZE_SANCTIONS_ALERT_COUNT = 1
FREEZE_SHORTFALL_CYCLES = 2
RESTRICT_BPS = 250
RESTRICT_VARIANCE_CENTS = 5_000_000
RESTRICT_GROWTH_BREACHES = 2
HEIGHTEN_BPS = 120
HEIGHTEN_GROWTH_BREACHES = 1
POSTURE_MULTIPLIERS = {
    "OPEN": 1.00,
    "HEIGHTENED": 1.25,
    "RESTRICTED": 1.50,
    "FROZEN": 2.00,
}

# --- reserve floor ------------------------------------------------------
ABSOLUTE_RESERVE_FLOOR_CENTS = 250_000
TRAILING_VOLUME_BPS = 150
TRAILING_WINDOW_DAYS = 90

# --- bank fee tiers -----------------------------------------------------
BANK_BASE_FEE_CENTS = 25_000
TIER_2_GROSS_FLOOR_CENTS = 10_000_000
TIER_3_GROSS_FLOOR_CENTS = 100_000_000
BANK_FEE_BPS_TIER_1 = 45
BANK_FEE_BPS_TIER_2 = 32
BANK_FEE_BPS_TIER_3 = 21

# --- complaint rate -----------------------------------------------------
COMPLAINT_TRAILING_DAYS = 90
COMPLAINT_RATE_SCALE = 10_000

# --- complaint response deadlines --------------------------------------
CALENDAR_DAY_SLA = {
    "CFPB_PORTAL": 15,
    "BANK_CALL_CENTER": 30,
    "PARTNER_APP": 30,
    "EMAIL": 30,
}
BUSINESS_DAY_SLA = {"STATE_AG": 10, "SOCIAL": 5}
BUSINESS_DAY_PIN_TIME = "23:59:59.999Z"

# --- alert SLA hours ----------------------------------------------------
ALERT_SLA_HOURS = {
    "SANCTIONS_HIT": 24,
    "STRUCTURING": 72,
    "VELOCITY": 120,
    "ACH_RETURN_RATE": 168,
}

# --- marketing cooling buffer ------------------------------------------
DISCLOSURE_COOLING_BUFFER_DAYS = 3

# --- growth -------------------------------------------------------------
ABSOLUTE_GROWTH_CAP_CENTS = 5_000_000

# --- wind-down ----------------------------------------------------------
MIN_NOTICE_DAYS = 30
MAX_NOTICE_DAYS = 180
REQUIRED_MILESTONES = ["RETURN_FUNDS", "CLOSE_CUSTODY"]

# --- pagination ---------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- shared test cycle periods -----------------------------------------
CYCLE_1_START = "2026-08-01T00:00:00Z"
CYCLE_1_END = "2026-09-01T00:00:00Z"
CYCLE_2_START = "2026-09-01T00:00:00Z"
CYCLE_2_END = "2026-10-01T00:00:00Z"
