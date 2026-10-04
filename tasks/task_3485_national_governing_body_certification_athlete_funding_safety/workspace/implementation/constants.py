"""Single source of truth for every named constant in the PRD/SCAFFOLD."""
from decimal import Decimal

# --- Logical clock -----------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Roles -------------------------------------------------------------------
ROLES = [
    "CommitteeAdmin",
    "CertificationAuditor",
    "NGBAdmin",
    "Athlete",
    "SafeSportOfficer",
    "Arbitrator",
    "ResultsOfficial",
]

# --- Compliance scoring (calculations.compliance_score) ----------------------
SCORE_WEIGHT_GOVERNANCE = Decimal("0.40")
SCORE_WEIGHT_ATHLETE_REP = Decimal("0.35")
SCORE_WEIGHT_FINANCIAL = Decimal("0.25")
COMPLIANCE_PASS_THRESHOLD = Decimal("70")
COMPLIANCE_EXCELLENT_THRESHOLD = Decimal("85")
REMEDIATION_BONUS_CAP = Decimal("10")
CYCLE_MAX_DURATION_DAYS = 120

# --- Funding points (calculations.funding_points) ----------------------------
PLACING_POINTS = {1: 40, 2: 32, 3: 26, 4: 20, 5: 16, 6: 12, 7: 8, 8: 4}
EVENT_MULTIPLIER = {"A": Decimal("1.5"), "B": Decimal("1.25"), "C": Decimal("1.0")}
RECENCY_FULL_DAYS = 180
RECENCY_HALF_WEIGHT = Decimal("0.5")
TRAILING_WINDOW_DAYS = 365

# --- Tier assignment (calculations.tier_assignment) --------------------------
TIER_A_MIN_POINTS = Decimal("100")
TIER_B_MIN_POINTS = Decimal("60")
TIER_C_MIN_POINTS = Decimal("30")
STIPEND_TIER_A_CENTS = 300000
STIPEND_TIER_B_CENTS = 200000
STIPEND_TIER_C_CENTS = 100000
STIPEND_BY_TIER = {
    "TIER_A": STIPEND_TIER_A_CENTS,
    "TIER_B": STIPEND_TIER_B_CENTS,
    "TIER_C": STIPEND_TIER_C_CENTS,
    "NONE": 0,
}

# --- Insurance (calculations.insurance_eligibility) --------------------------
INSURANCE_MIN_POINTS = Decimal("60")
INSURANCE_WAIT_DAYS = 30

# --- Roster composite ranking (calculations.roster_composite_ranking) --------
COMPOSITE_TRIALS_WEIGHT = Decimal("0.7")
COMPOSITE_SEASON_WEIGHT = Decimal("0.3")
ALTERNATE_COUNT = 2
TRAINING_VALIDITY_DAYS = 365

# --- Quota bonus (calculations.quota_bonus) ----------------------------------
QUOTA_BONUS_THRESHOLD = Decimal("250")
QUOTA_BONUS_SLOTS = 1

# --- Revenue split (calculations.revenue_split) ------------------------------
COMMITTEE_SHARE_PCT = Decimal("0.30")
NGB_SHARE_PCT = Decimal("0.40")
AGENCY_FEE_PCT = Decimal("0.10")

# --- Science-hours waterfall (calculations.science_hours_waterfall) ----------
SCIENCE_HOURS_CAP_A = 40
SCIENCE_HOURS_CAP_B = 25
SCIENCE_HOURS_CAP_C = 10
SCIENCE_HOURS_CAP = {
    "TIER_A": SCIENCE_HOURS_CAP_A,
    "TIER_B": SCIENCE_HOURS_CAP_B,
    "TIER_C": SCIENCE_HOURS_CAP_C,
}

# --- Complaint posture (calculations.complaint_posture) ----------------------
COMPLAINT_POSTURE_THRESHOLD = 3
COMPLAINT_POSTURE_WINDOW_DAYS = 365

# --- Safe-sport validity windows ---------------------------------------------
SCREENING_VALIDITY_DAYS = 730

# --- Selection procedure gating ----------------------------------------------
MIN_PUBLISH_LEAD_DAYS = 90
REGISTRATION_CLOSE_BEFORE_TRIALS_DAYS = 14
APPEAL_WINDOW_HOURS = 72

# --- Commercial deal exclusivity ----------------------------------------------
DEAL_EXCLUSIVITY_MIN_GAP_DAYS = 1

# --- Pagination ---------------------------------------------------------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# --- Shared role lists ----------------------------------------------------------
ALL_ROLES_READ = ["CommitteeAdmin", "CertificationAuditor", "NGBAdmin",
                  "SafeSportOfficer", "Arbitrator", "Athlete", "ResultsOfficial"]

# Body standings that permit selection/deal activity
BODY_STANDING_OK = ("CERTIFIED", "PROBATION", "INTERIM_MANAGED")
