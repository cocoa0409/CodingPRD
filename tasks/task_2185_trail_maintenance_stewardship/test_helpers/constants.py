"""Domain thresholds and shared literals drawn from the PRD narrative."""

# Logical clock (PRD section 2.5)
CLOCK_START = "2026-08-01T00:00:00.000Z"

# Segment posture (PRD section 2.6)
POSTURE_THRESHOLDS = {
    "HAZARD_INDEX_RESTRICT": 60,
    "WET_FRESHNESS_HOURS": 72,
}

# Priority scoring (PRD section 3.4)
SEVERITY_BASE = {
    "LOW": 20,
    "MODERATE": 50,
    "HIGH": 80,
    "CRITICAL": 100,
}
EXPOSURE_MULTIPLIER = {
    "LOW": 0.8,
    "MEDIUM": 1.0,
    "HIGH": 1.25,
}
TRAFFIC_MULTIPLIER = {
    "LIGHT": 0.9,
    "MODERATE": 1.0,
    "HEAVY": 1.15,
}
PRIORITY_THRESHOLDS = {
    "AGE_BONUS_PER_WEEK": 3,
    "AGE_BONUS_CAP": 15,
    "WET_SURCHARGE": 8,
    "ESCALATION_THRESHOLD": 70,
    "SCORE_CAP": 100,
}

# Hazard index (PRD section 3.4)
HAZARD_STATUS_WEIGHT = {
    "TRIAGED": 1.0,
    "SCHEDULED": 1.0,
    "DEFERRED": 0.5,
    "ESCALATED": 1.5,
}
HAZARD_DIVISOR = 3
ESCALATION_OVERRIDE_COUNT = 2

# Hour crediting (PRD section 3.7)
HOUR_RULES = {
    "BREAK_THRESHOLD_MIN": 240,
    "BREAK_DEDUCTION_MIN": 30,
    "TRAVEL_CAP_MIN": 60,
    "QUANTUM_MIN": 15,
    "QUANTUM_HOURS": 0.25,
}

# Roster and coverage (PRD sections 3.6 and 3.7)
ROSTER_RULES = {
    "FIRST_AID_RATIO_DIVISOR": 8,
    "FIRST_AID_MINIMUM": 1,
    "SEGMENT_BUFFER_MINUTES": 60,
    "VOLUNTEER_DAILY_HOUR_CAP": 10.0,
}

# Budget ledger and pricing (PRD sections 3.3 and 3.8)
BUDGET_RULES = {
    "TIGHT_FLOOR_FRACTION": 0.20,
    "ADMISSION_CAP_FRACTION": 1.20,
}
PRICING = {
    "DISCOUNT_TIER_1_MIN_CENTS": 50_000,
    "DISCOUNT_TIER_1_PCT": 0.04,
    "DISCOUNT_TIER_2_MIN_CENTS": 250_000,
    "DISCOUNT_TIER_2_PCT": 0.07,
    "FREIGHT_FREE_THRESHOLD_CENTS": 200_000,
    "FREIGHT_BASE_CENTS": 4_500,
    "FREIGHT_PCT": 0.02,
    "BRIDGE_SURCHARGE_PCT": 0.06,
}

# Grant match (PRD section 3.7)
SKILL_CLASS_RATE_USD = {
    "GENERAL": 28.54,
    "SKILLED_TRAIL": 41.20,
    "CERTIFIED_SAWYER": 63.75,
    "PROFESSIONAL": 89.00,
}
PROVISIONAL_FLAT_RATE_USD = 28.54

# Agency policy defaults (PRD section 3.1)
LAND_MANAGER_DEFAULTS = {
    "permit_required": True,
    "permit_lead_days": 14,
    "max_party_size": 20,
    "wet_threshold_index": 0.65,
    "requires_engineering_review": False,
    "requires_certified_sawyer": True,
    "policy_version": 1,
    "adopted_segment_count": 0,
}

# Revision loops (PRD sections 3.2 and 3.3)
REVISION_LIMIT = 3

# Operator identities used by the opaque roles.
COORDINATOR_USER_ID = "coord-1"
SAFETY_OFFICER_USER_ID = "safety-1"
SAFETY_OFFICER_ALT_USER_ID = "safety-2"
GRANTS_ADMIN_USER_ID = "grants-1"

# Shared fixture literals.
TEST_DEFAULTS = {
    "AGENCY_NAME": "Cascade National Forest",
    "JURISDICTION_CODE": "USFS-R6-ALDER",
    "SEGMENT_NAME": "Alder Creek",
    "SEGMENT_LENGTH_MILES": 4.2,
    "PLAN_BUDGET_CENTS": 250_000,
    "SEASON_YEAR": 2026,
    "TERM_START_DATE": "2026-08-01",
    "TERM_END_DATE": "2027-07-31",
    "PERMIT_WINDOW_START": "2026-09-01",
    "PERMIT_WINDOW_END": "2026-09-30",
    "PARTY_START_AT": "2026-09-05T09:00:00.000Z",
    "PARTY_END_AT": "2026-09-05T15:00:00.000Z",
}

ALL_WORK_TYPES = [
    "TREAD_WORK",
    "CHAINSAW",
    "SIGNAGE",
    "BRUSHING",
    "DRY_WORK",
    "BRIDGE_CONSTRUCTION",
]
