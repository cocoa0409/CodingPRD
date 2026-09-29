"""Domain thresholds and numeric constants drawn from the PRD's derivations.

Every value here is quoted from the PRD prose (§2.4, §2.8, §3.1, §3.4, §3.6,
§3.7, §3.9); nothing is invented.
"""

# --- The logical park clock (PRD §2.4) ---------------------------------------
# "At process start the logical clock reads exactly `2026-08-01T00:00:00Z`"
CLOCK_START_INSTANT = "2026-08-01T00:00:00.000Z"
CLOCK_START_DATE = "2026-08-01"

# --- Pagination (PRD §2.3) ---------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "DEFAULT_OFFSET": 0,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
}

# --- Nondestructive testing intervals (PRD §3.1) ----------------------------
NDT = {
    # "multiplied by a grace factor of 1.20 and rounded up to a whole number"
    "GRACE_FACTOR": 1.20,
}

# --- Downtime capacity impact (PRD §3.4) ------------------------------------
CAPACITY = {
    # "peak window runs from 11:00 UTC ... up to but not including 17:00 UTC"
    "PEAK_WINDOW_START_HOUR_UTC": 11,
    "PEAK_WINDOW_END_HOUR_UTC": 17,
    "PEAK_WEIGHT": 1.00,
    "OFF_PEAK_WEIGHT": 0.55,
    # "the rounded raw figure is multiplied by 0.85"
    "PROVISIONAL_RECOVERY_MULTIPLIER": 0.85,
    # "when it is omitted it defaults to 120" (mean_repair_minutes, PRD §3.1)
    "DEFAULT_MEAN_REPAIR_MINUTES": 120,
}

# --- Bulletin fleet risk scoring (PRD §3.6) ---------------------------------
BULLETIN_RISK = {
    "OVERDUE_POINTS_PER_DAY": 1.5,
    "OVERDUE_POINTS_CAP": 30,
    "SEVERITY_BASE": {"ADVISORY": 10, "MANDATORY": 40, "RECALL": 70},
    "RIDE_CLASS_FACTOR": {"KIDDIE": 0.6, "FAMILY": 0.8, "WATER": 1.0, "THRILL": 1.2},
    "STATUS_FACTOR": {"PENDING": 1.0, "IN_WORK": 0.6, "DEFERRED": 1.4},
    "SCORE_CEILING": 100,
    "ESCALATION_PER_DEFERRAL": 0.05,
}

# --- Certification and dispatch readiness (PRD §3.7) ------------------------
CERTIFICATION = {
    "RESTRAINT_SCORE_THRESHOLD": 85,
    "DISPATCH_SCORE_THRESHOLD": 80,
    "SCORE_MIN": 0,
    "SCORE_MAX": 100,
}

DISPATCH_READINESS = {
    "RESTRAINT_FLOOR": 60,
    "RESTRAINT_SPAN": 40,
    "BASE_WEIGHT": 0.40,
    "RESTRAINT_WEIGHT": 0.60,
    "PENALTY_PER_ESSENTIAL_FAIL": 8,
    "PENALTY_CAP": 40,
    "STAFFING_RATIO_CAP": 1.0,
}

# --- Incidents (PRD §3.8) ---------------------------------------------------
INCIDENT = {
    "NOTIFICATION_WINDOW_HOURS": 24,
    "HOLD_SUSPENSION_REASON": "RIDE_HOLD",
}

# --- Overhaul cost estimate (PRD §3.9) --------------------------------------
OVERHAUL = {
    "LABOR_RATE_CENTS_PER_HOUR": 9500,
    "OFF_SEASON_DISCOUNT_PCT": 0.06,
    "EXPEDITE_TIER_1_CEILING_CENTS": 5_000_000,
    "EXPEDITE_TIER_2_CEILING_CENTS": 20_000_000,
    "EXPEDITE_PCT_TIER_1": 0.12,
    "EXPEDITE_PCT_TIER_2": 0.08,
    "EXPEDITE_PCT_TIER_3": 0.05,
    "CHANGEOVER_BUFFER_DAYS": 1,
}

# --- Enumerated value sets (PRD §3) -----------------------------------------
PARK_AREAS = ["FRONTIER", "LAGOON", "SKYLINE", "KIDS_COVE"]
RIDE_CLASSES = ["KIDDIE", "FAMILY", "THRILL", "WATER"]
COMPONENT_TYPES = [
    "BRAKE",
    "LIFT_CHAIN",
    "RESTRAINT_ACTUATOR",
    "GEARBOX",
    "AXLE",
    "CONTROL_PLC",
]
CRITICALITIES = ["SAFETY_CRITICAL", "ESSENTIAL", "NON_CRITICAL"]
NDT_METHODS = [
    "MAGNETIC_PARTICLE",
    "ULTRASONIC",
    "DYE_PENETRANT",
    "EDDY_CURRENT",
    "VISUAL",
]
SEVERITY_CLASSES = ["SAFETY_CRITICAL", "ESSENTIAL", "ADVISORY"]
INSPECTION_OUTCOMES = ["PENDING", "PASS", "FAIL", "NA"]
CAUSE_CATEGORIES = [
    "MECHANICAL",
    "ELECTRICAL",
    "GUEST_ILLNESS",
    "WEATHER",
    "INSPECTION_FAIL",
    "OPERATOR",
]
BULLETIN_SEVERITIES = ["ADVISORY", "MANDATORY", "RECALL"]
INJURY_SEVERITIES = ["NONE", "MINOR", "SERIOUS", "FATAL"]
OPERATIONAL_POSTURES = [
    "OPEN",
    "CLOSED_PENDING_INSPECTION",
    "DOWN",
    "HOLD",
    "OVERHAUL",
]

# --- The live-downtime set used by two rules (PRD §2.8 clause 3, §2.6 #21) ---
LIVE_DOWNTIME_STATUSES = ["OPEN", "DIAGNOSED", "AWAITING_PARTS", "RESOLVED"]

# --- The committed-requisition set (PRD §2.9) --------------------------------
COMMITTED_REQUISITION_STATUSES = ["RESERVED", "BACKORDERED", "RECEIVED"]

# --- Convenient test defaults ----------------------------------------------
TEST_DEFAULTS = {
    "THEORETICAL_HOURLY_CAPACITY": 900,
    "MIN_OPERATORS_REQUIRED": 2,
    "PARTS_BUDGET_CENTS": 1_000_000,
    "NDT_INTERVAL_CYCLES": 500_000,
    "NDT_INTERVAL_DAYS": 3650,
}
