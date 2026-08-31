"""Domain thresholds and defaults quoted from the PRD narrative."""

# Declared defaults of an evaluation policy (PRD §2.5).
POLICY_DEFAULTS = {
    "observation_weight_pct": 60,
    "growth_weight_pct": 40,
    "planning_weight_pct": 22,
    "environment_weight_pct": 23,
    "instruction_weight_pct": 33,
    "professionalism_weight_pct": 22,
    "required_formal_count": 2,
    "required_informal_count": 1,
    "unannounced_multiplier": 1.10,
    "informal_cap": 3.50,
    "highly_effective_threshold": 3.50,
    "effective_threshold": 2.50,
    "developing_threshold": 1.50,
    "evidence_min_artifacts": 2,
    "remediation_days": 90,
    "max_plan_extension_days": 45,
    "appeal_window_days": 15,
    "tenure_required_years": 3,
    "tenure_min_consecutive_effective": 2,
    "min_days_between_formals": 10,
    "calibration_drift_tolerance": 0.50,
    "calibration_max_consecutive_failures": 2,
    "observation_stipend_cents": 12500,
}

# Fixed numbers the PRD narrative states outside the policy row.
SCORE_FLOOR = 1.00            # PRD §2.6 four-point scale floor
SCORE_CEILING = 4.00          # PRD §2.6 four-point scale ceiling
MISSING_OBSERVATION_FLOOR = 1.00   # PRD §3.6 FINAL-variant padding value
FORMAL_SHARE = 0.75           # PRD §3.5 formal share of the observation component
INFORMAL_SHARE = 0.25         # PRD §3.5 informal share
INFORMAL_STIPEND_RATIO = 0.4  # PRD §3.5 informal rate is 0.4 of the formal one
CERTIFICATION_TERM_DAYS = 365  # PRD §3.2 one-year certification term
DAYS_PER_SERVICE_YEAR = 365    # PRD §3.9 service-year arithmetic
RELIABILITY_FLOOR = 0.60       # PRD §3.6 reliability factor floor
OUTLIER_HIGHLY_EFFECTIVE_PCT = 35.00  # PRD §3.9 distribution outlier threshold
EVIDENCE_BONUS = 0.05          # PRD §3.6 evidence-sufficiency bonus
EVIDENCE_PENALTY = 0.10        # PRD §3.6 evidence-sufficiency penalty

# The logical district clock before any operator sets it (PRD §2.11).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Well-formed UUIDs that name nothing.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
MISSING_UUIDS = [
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
    "00000000-0000-4000-8000-000000000004",
    "00000000-0000-4000-8000-000000000005",
]

SCHOOL_YEAR = "2026-2027"
