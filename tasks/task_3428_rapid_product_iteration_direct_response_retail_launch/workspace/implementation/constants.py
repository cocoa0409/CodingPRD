"""Named constants — every threshold/weight referenced anywhere is pinned here
exactly once (mirrors SCAFFOLD.yaml `constants:`; values are authoritative).

Decimal-typed knobs are stored as strings so `Decimal(CONSTANTS[name])` is exact.
"""

CONSTANTS = {
    # logical clock
    "CLOCK_DEFAULT_ISO": "2026-09-01T00:00:00Z",
    # research momentum
    "RESEARCH_DECAY_PER_WEEK": "0.85",
    "RESEARCH_SCORE_MIN": "40.0",
    "CONCEPT_MAX_AGE_DAYS": 120,
    # prototype rounds
    "ROUND_MAX_OPEN_DAYS": 21,
    "MAX_ROUNDS_PER_CYCLE": 4,
    "ROUND_PASS_SCORE": 75,
    # claims
    "CLAIM_MIN_MARGIN": "0.15",
    "CLAIM_MIN_SAMPLES": 30,
    # media
    "AGENCY_COMMISSION_RATE": "0.15",
    "MER_SCALE_MIN": "2.0",
    "MEDIA_DECISION_MAX_DAYS": 28,
    # patent exposure / reserve
    "PRIOR_ADVERSE_PROB": "0.30",
    "CASE_WEIGHT_LOW": 2,
    "CASE_WEIGHT_MED": 5,
    "CASE_WEIGHT_HIGH": 9,
    "ADVERSE_WEIGHT_MULTIPLIER": 3,
    "EXPOSURE_ELEVATED_MIN": 8,
    "EXPOSURE_SEVERE_MIN": 20,
    "GUARDED_GRACE_REVIEWS": 2,
    # commitments / replenishment
    "SHORTFALL_PENALTY_CENTS": 150,
    "COVER_WEEKS": 3,
    "REPLENISH_MIN_WEEKLY_UNITS": 50,
    # refresh cadence
    "MODEL_MAX_AGE_DAYS": 240,
    "REFRESH_GRACE_DAYS": 30,
    # tooling
    "TOOLING_WINDOW_DAYS": 14,
    "TOOLING_PARALLEL_SLOTS": 2,
}
