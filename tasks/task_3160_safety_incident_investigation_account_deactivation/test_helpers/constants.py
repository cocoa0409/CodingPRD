"""Domain thresholds — numeric constants the safety pipeline reads."""

# The startup default logical time before POST /_clock/set_current_utc is called.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

DAYS = 86400

# --- Severity classification (PRD §2.7, §3.1) ------------------------------
SEVERITY_BASE_LEVEL = {
    "PHYSICAL_ASSAULT": 4,
    "SEXUAL_MISCONDUCT": 4,
    "HARASSMENT": 2,
    "SAFETY_VIOLATION": 2,
    "FRAUD_IDENTITY": 2,
    "DISCRIMINATION": 2,
    "PROPERTY_DAMAGE": 1,
}
AGGRAVATOR_LEVELS = {
    "S3_INJURY": 1,
    "S3_LAW_ENFORCEMENT_SEVERITY": 1,
}
BAND_MAX_LEVEL = 4
BAND_MIN_LEVEL = 1
SEVERITY_LEVEL = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}

# --- Evidence admissibility (PRD §3.3) -------------------------------------
EVIDENCE_BASE_WEIGHT = {
    "WEAK": 0.40,
    "STANDARD": 0.70,
    "STRONG": 1.00,
    "DISPOSITIVE": 1.50,
}
RELIABILITY_DEFAULT = 0.95
RELIABILITY_EXTERNAL_RECORD = 0.75
RELIABILITY_MESSAGE_OR_RATINGS = 0.90
CAP_IN_APP_MESSAGE = 0.80
CAP_RATINGS_HISTORY = 0.80
CAP_LAW_ENFORCEMENT_CONTACT = 0.70
CAP_DEFAULT = 1.00
CAP_PENALTY_PER_MISSING_SOURCE = 0.15
DISPOSITIVE_PROMOTION_SCORE = 3.00
DISPOSITIVE_CONFIDENCE_FLOOR = 0.80
DISPOSITIVE_MIN_DISTINCT_SOURCES = 2
STALE_LINK_MAX_AGE_DAYS = 180
SUPPORT_EVIDENCE_TYPES = ("TRIP_DATA", "RATINGS_HISTORY", "LAW_ENFORCEMENT_CONTACT")

# --- Risk contagion (PRD §2.4) ---------------------------------------------
RISK_BASE = {"S1": 20, "S2": 60, "S3": 140, "S4": 260}
DECAY_STEP_1_DAYS = 90
DECAY_STEP_2_DAYS = 180
DECAY_FACTOR_STEP_1 = 0.50
DECAY_FACTOR_STEP_2 = 0.00
ENFORCEMENT_ACTIVE_WEIGHT = 180
CLUSTER_TERM_COEFFICIENT = 0.25
SCORE_CEILING = 1000
SCORE_FLOOR = 0
TIER_SEVERE_CUTOFF = 640
TIER_HIGH_CUTOFF = 420
TIER_ELEVATED_CUTOFF = 210
TIER_SEVERE_RESCUE_SCORE_CEILING = 400
CLEAR_ADJUDICATION_CREDIT = 15
INCONCLUSIVE_ADJUDICATION_DEBIT = 30
COMPLETED_TRIP_CREDIT = 2

# --- Decision criteria (PRD §3.4) ------------------------------------------
SCORE_DEACTIVATION = 4.00
SCORE_PROVISIONAL_DEACTIVATION = 2.50
MIN_DISTINCT_SOURCES = 2
HARASSMENT_PRIOR_S3_S4_COUNT = 2
SAFETY_VIOLATION_PRIOR_S3_S4_COUNT = 3
INVESTIGATION_SCOPE_DIVISOR = 5
INVESTIGATION_SCOPE_RATIO_FLOOR = 0.70
PROPERTY_DAMAGE_WARNING_SCORE = 1.50
WARNING_SUPPORT_FLOOR = 2.0
DECISION_TIER_RANK = {
    "NO_ACTION": 0,
    "WARNING": 1,
    "RESTRICTED": 2,
    "DEACTIVATED": 3,
}

# --- Graduated rollup (PRD §3.7) -------------------------------------------
ROLLUP_COUNT = 5
ROLLUP_CATEGORY_RANK = {
    "PHYSICAL_ASSAULT": 0,
    "SEXUAL_MISCONDUCT": 1,
    "HARASSMENT": 2,
    "SAFETY_VIOLATION": 3,
    "FRAUD_IDENTITY": 4,
    "DISCRIMINATION": 5,
    "PROPERTY_DAMAGE": 6,
}

# --- Regulator reporting (PRD §3.5) ----------------------------------------
ROLLUP_WINDOW_DAYS = 30
ROLLUP_THRESHOLD = 3
REPORTABLE_CATEGORIES = ("PHYSICAL_ASSAULT", "SEXUAL_MISCONDUCT")
REPORTABLE_SEVERITIES = ("S3", "S4")

# --- Expiry sweep (PRD §3.8) -----------------------------------------------
EXPIRY_SIMULATION_PENALTY = 30

# --- Scheduled intervals ----------------------------------------------------
REVIEW_INTERVAL_DAYS = 180
RESTRICTION_HORIZON_DAYS = 365
APPEAL_WINDOW_DAYS = 30
DORMANCY_DAYS = 180
SEVERANCE_DAYS = 365
RESCREEN_INTERVAL_DAYS = 548
DRIFT_INDEX_DIVISOR = 3

# --- Appeal track (PRD §3.6) -----------------------------------------------
EXPEDITE_APPEAL_BASELINE_COUNT = 5
EXPEDITE_REVIEW_DAYS = 14
STANDARD_REVIEW_DAYS = 30

# --- Policy defaults (PRD §3.9) --------------------------------------------
POLICY_DEFAULTS = {
    "sd_floor_enabled": True,
    "rollup_window_days": 30,
    "rollup_threshold": 3,
    "cluster_watchlist_threshold": 2,
    "cluster_purge_threshold": 2400,
    "escalation_enabled": True,
    "expedite_appeal_baseline_count": 5,
    "expedite_review_days": 14,
    "standard_review_days": 30,
    "appeal_window_days": 30,
    "rescreen_refresh_days": 548,
    "continuous_monitor_ack_deadline_days": 7,
    "review_generation_index": 1,
    "knob_generation_index": 1,
}

# --- Scenario defaults used by factories/fixtures ---------------------------
TEST_DEFAULTS = {
    "REGION": "R1",
    "POLICY_SD_FLOOR_SEVERITY": "S4",
    "CLOCK": "2026-10-01T00:00:00Z",
    "TRIP_REQUESTED_AT": "2026-09-28T00:00:00Z",
}