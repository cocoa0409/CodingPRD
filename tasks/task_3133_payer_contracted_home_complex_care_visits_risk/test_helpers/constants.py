"""Domain thresholds — numeric constants from the PRD's calculation narratives."""

# Chronic condition weights (PRD section 3.2)
CONDITION_WEIGHT = {
    "CHF": 6,
    "COPD": 5,
    "CKD": 4,
    "DIABETES": 3,
    "DEMENTIA": 7,
    "DEPRESSION": 2,
    "HTN": 1,
}
ED_VISIT_WEIGHT = 3
IP_ADMIT_WEIGHT = 5

# Risk tier thresholds (PRD section 3.2)
TIER_MEDIUM_MIN = 8
TIER_HIGH_MIN = 15
TIER_VERY_HIGH_MIN = 25

# Composite score weights (PRD section 3.7)
SLA_WEIGHT = 0.40
ED_AVOID_WEIGHT = 0.30
VISIT_COMPLETION_WEIGHT = 0.20
PCP_COORDINATION_WEIGHT = 0.10

# Workflow caps (PRD sections 3.3 and 3.5)
MAX_OUTREACH_ATTEMPTS = 3
MAX_RESCHEDULES = 2

# Default logical clock at server startup (PRD section 2.4)
DEFAULT_CLOCK_START = "2026-09-01T00:00:00Z"
