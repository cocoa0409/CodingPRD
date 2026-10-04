"""Domain constants — every value taken from PRD.md calculations and workflows.

No placeholders: each constant carries the PRD-true value, defined exactly once.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
VISIT_START_ISO = "2027-03-10T09:00:00Z"
VISIT_END_ISO = "2027-03-12T17:00:00Z"
POST_VISIT_CLOCK_ISO = "2027-03-12T18:00:00Z"
CURE_REVIEW_NEXT_DAY_ISO = "2026-09-02T00:00:00Z"
CANDIDACY_PAST_EXPIRY_ISO = "2031-01-01T00:00:00Z"

# --- Candidacy pathways (PRD §3.2) -------------------------------------------
CANDIDACY_YEARS = {"STANDARD": 4, "ACCELERATED": 2}

# --- Annual dues assessment (PRD §3.1) ---------------------------------------
BASE_DUES_CENTS = 250000
DUES_RATE_CENTS = {"ASSOCIATE": 33, "BACCALAUREATE": 45, "MASTERS": 61, "DOCTORAL": 83}
DUES_MULTIPLIER = {"ASSOCIATE": 1.00, "BACCALAUREATE": 1.00, "MASTERS": 1.15, "DOCTORAL": 1.35}
DEGREE_LEVELS = ["ASSOCIATE", "BACCALAUREATE", "MASTERS", "DOCTORAL"]

# Canonical dues totals (per-line round-half-up, then sum, then base)
DUES_CANONICAL_800_A_B = 312400      # 250000 + 800*33 + 800*45
DUES_900_A_B = 320200                # after PATCH fte 900
DUES_1003_A_M_D = 465845             # per-line rounding pinned (not 465846)
DUES_800_A_B_M = 368520              # PROGRAM_LEVEL MASTERS approved: + 800*61*1.15 = 56120
ARREARS_AFTER_FTE_900 = 7800         # 320200 - 312400

# --- Composite Financial Index (PRD §3.9) ------------------------------------
CFI_SCALE_MIN = -4.00
CFI_SCALE_MAX = 10.00
CFI_WEIGHTS_PRIVATE = {
    "primary_reserve_ratio": 0.40,
    "viability_ratio": 0.35,
    "net_operating_ratio": 0.25,
}
CFI_WEIGHTS_PUBLIC = {"primary_reserve_ratio": 0.50, "viability_ratio": 0.50}
APPROPRIATION_BONUS = 0.50
APPROPRIATION_MIN_RATIO = 0.20
CFI_CLEAR_ABOVE = 1.10
CFI_PANEL_AT_OR_BELOW = -0.90

# --- Enrollment Momentum Index (PRD §3.9) ------------------------------------
COMPLETION_NEUTRAL_PCT = 50.0
RETENTION_NEUTRAL_PCT = 70.0
EMI_FLAG_BELOW = -5.00

# --- Assurance readiness (PRD §3.4) ------------------------------------------
CRITERION_CODES = [
    "CRIT_MISSION",
    "CRIT_INTEGRITY",
    "CRIT_TEACHING_QUALITY",
    "CRIT_TEACHING_EVALUATION",
    "CRIT_RESOURCES_PLANNING",
]
MIN_EVIDENCE_PER_CRITERION = 3
ARGUMENT_MIN_TOTAL_EVIDENCE = 15
MAX_ARGUMENT_REVISIONS = 2
READINESS_WEIGHTS = {
    "CRIT_MISSION": 0.15,
    "CRIT_INTEGRITY": 0.25,
    "CRIT_TEACHING_QUALITY": 0.25,
    "CRIT_TEACHING_EVALUATION": 0.15,
    "CRIT_RESOURCES_PLANNING": 0.20,
}
# 15 items: exactly the minimum coverage (3 per criterion)
EVIDENCE_PLAN_STANDARD = {code: MIN_EVIDENCE_PER_CRITERION for code in CRITERION_CODES}
# 16 items: one extra TEACHING_QUALITY item (coverage still capped at 1.0)
EVIDENCE_PLAN_TEACHING_QUALITY_EXTRA = {
    **EVIDENCE_PLAN_STANDARD,
    "CRIT_TEACHING_QUALITY": 4,
}
# 9 verified items -> TEAM_VERIFIED readiness 60.00
READINESS_VERIFIED_PLAN_9 = {
    "CRIT_MISSION": 3,
    "CRIT_INTEGRITY": 2,
    "CRIT_TEACHING_QUALITY": 1,
    "CRIT_TEACHING_EVALUATION": 0,
    "CRIT_RESOURCES_PLANNING": 3,
}
EXPECTED_READINESS_SELF_FULL = 100.00
EXPECTED_READINESS_VERIFIED_9 = 60.00
EXPECTED_READINESS_AFTER_UNVERIFY = 51.67

# --- Recommended action determination (PRD §3.6) -----------------------------
RATING_POINTS = {"MET": 4, "MET_WITH_CONCERNS": 2, "NOT_MET": 0}
REAFFIRM_MIN_POINTS = 18
NOTICE_MIN_POINTS = 12
PROBATION_MIN_POINTS = 8

# --- Decision panel (PRD §3.7) -----------------------------------------------
PANEL_SIZE = 7
PANEL_QUORUM = 5
VOTE_SEVERITY = {
    "WITHDRAW": 7,
    "SHOW_CAUSE": 6,
    "PROBATION": 5,
    "NOTICE": 4,
    "DENY": 3,
    "REAFFIRM": 2,
    "GRANT": 1,
}
VOTE_TO_ACTION_TYPE = {
    "GRANT": "GRANT_INITIAL",
    "DENY": "DENIAL",
    "WITHDRAW": "WITHDRAWAL",
    "REAFFIRM": "REAFFIRMATION",
    "NOTICE": "NOTICE",
    "PROBATION": "PROBATION",
    "SHOW_CAUSE": "SHOW_CAUSE",
}

# --- Team assembly (PRD §3.5) -------------------------------------------------
TEAM_MEMBER_MIN = 3
CHAIR_MIN_PRIOR_VISITS = 2
MAX_CONCURRENT_ASSIGNMENTS = 3
ONSITE_BUFFER_DAYS = 1
VIRTUAL_BUFFER_DAYS = 0

# --- Cohort default rates (PRD §3.3) -----------------------------------------
CDR_SINGLE_YEAR_PCT = 40.0
CDR_CONSECUTIVE_YEAR_PCT = 30.0

# --- Sanction cure (PRD §3.8) -------------------------------------------------
BASE_CURE_SCORE = 60
SANCTION_LEVEL_OFFSET = {"NOTICE": 0, "PROBATION": 15, "SHOW_CAUSE": 30}
CLEARED_REPORT_POINTS = 25
CURE_SCORE_CAP = 100
SANCTION_CURE_MONTHS = {"NOTICE": 12, "PROBATION": 24, "SHOW_CAUSE": 12}
EXPECTED_CURE_SNAPSHOT_NOTICE = 60
EXPECTED_CURE_SNAPSHOT_PROBATION = 75
EXPECTED_CURE_SNAPSHOT_SHOW_CAUSE = 90

# --- Canonical indicator metric sets (PRD §3.9 formulas applied) --------------
# Financially healthy: CFI 1.72 (CLEAR band); EMI -4.00 (not flagging)
INDICATOR_METRICS_HEALTHY = {
    "primary_reserve_ratio": 0.12,
    "viability_ratio": 0.08,
    "net_operating_ratio": 0.04,
    "enrollment_change_pct": -9.0,
    "completion_rate": 51.0,
    "retention_rate": 71.0,
    "fte_enrollment": 800,
}
EXPECTED_CFI_HEALTHY = 1.72
EXPECTED_EMI_HEALTHY = -4.00

# EMI boundary: EMI exactly -5.00 -> NOT flagged (CFI still 1.72 CLEAR)
INDICATOR_METRICS_EMI_BOUNDARY = {
    **INDICATOR_METRICS_HEALTHY,
    "enrollment_change_pct": -10.0,
    "completion_rate": 50.0,
    "retention_rate": 70.0,
}
EXPECTED_EMI_BOUNDARY = -5.00

# Panel band: CFI -1.55 (<= -0.90) -> FLAGGED_PANEL + sanction cascade
INDICATOR_METRICS_PANEL_BAND = {
    "primary_reserve_ratio": -0.10,
    "viability_ratio": -0.05,
    "net_operating_ratio": -0.08,
    "enrollment_change_pct": -9.0,
    "completion_rate": 51.0,
    "retention_rate": 71.0,
    "fte_enrollment": 800,
}
EXPECTED_CFI_PANEL_BAND = -1.55

# CFI boundary: CFI exactly 1.10 -> REVIEW band (not strictly above 1.10)
INDICATOR_METRICS_CFI_BOUNDARY = {
    "primary_reserve_ratio": 0.05,
    "viability_ratio": 0.05,
    "net_operating_ratio": 0.07,
    "enrollment_change_pct": -9.0,
    "completion_rate": 51.0,
    "retention_rate": 71.0,
    "fte_enrollment": 800,
}
EXPECTED_CFI_BOUNDARY = 1.10

# Variant divergence: identical ratios -> PRIVATE 1.25 / PUBLIC 2.00
INDICATOR_METRICS_VARIANT_PRIVATE = {
    "primary_reserve_ratio": 0.10,
    "viability_ratio": 0.05,
    "net_operating_ratio": 0.02,
    "enrollment_change_pct": -9.0,
    "completion_rate": 51.0,
    "retention_rate": 71.0,
    "fte_enrollment": 800,
}
INDICATOR_METRICS_VARIANT_PUBLIC = {
    **INDICATOR_METRICS_VARIANT_PRIVATE,
    "state_appropriation_ratio": 0.25,
}
EXPECTED_CFI_PRIVATE_VARIANT = 1.25
EXPECTED_CFI_PUBLIC_VARIANT = 2.00

# --- Federal compliance defaults (PRD §3.3) -----------------------------------
FEDERAL_COMPONENT_CODES = ["CREDIT_HOUR_POLICY", "STATE_AUTHORIZATION", "DEFAULT_MANAGEMENT"]
CDR_RATES_COMPLIANT = [12.5, 14.0, 11.2]
CDR_RATES_BOUNDARY_DEFICIENT = [30.0, 30.0, 30.0]
CDR_RATES_SINGLE_YEAR_DEFICIENT = [12.0, 40.0]
CDR_RATES_SINGLE_YEAR_COMPLIANT = [12.0, 39.9]

# --- Standard indicator periods (closed intervals, contiguous tiling) ---------
PERIOD_2026 = ("2026-01-01", "2026-12-31")
PERIOD_2027 = ("2027-01-01", "2027-12-31")
PERIOD_2028 = ("2028-01-01", "2028-12-31")
PERIOD_2029 = ("2029-01-01", "2029-12-31")
