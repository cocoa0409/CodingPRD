"""Domain thresholds and shared literals drawn from the PRD's stated formulae."""

# The logical clock's startup value (PRD section 2.4).
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# Referral triage scoring (PRD section 3.3).
TRIAGE = {
    "LOOKBACK_DAYS": 21,
    "TREND_WEIGHT": 1.2,
    "TREND_POINTS_CAP": 40,
    "FLOW_CRITICAL_ML_MIN": 600,
    "FLOW_LOW_ML_MIN": 800,
    "TREND_LEVEL_CRITICAL_POINTS": 25,
    "TREND_LEVEL_LOW_POINTS": 12,
    "ABSOLUTE_LEVEL_CRITICAL_POINTS": 40,
    "ABSOLUTE_LEVEL_LOW_POINTS": 20,
    "VENOUS_PRESSURE_HIGH_MMHG": 150,
    "VENOUS_PRESSURE_POINTS": 15,
    "RECIRCULATION_HIGH_PCT": 10.0,
    "RECIRCULATION_POINTS": 10,
    "MISSED_POINTS_PER": 6,
    "MISSED_POINTS_CAP": 18,
    "SCORE_CAP": 100,
    "SAME_DAY_SCORE_MIN": 70,
    "NEXT_DAY_SCORE_MIN": 45,
}

# Facility partnership scoring (PRD section 3.4).
PARTNERSHIP = {
    "WINDOW_DAYS": 90,
    "GRACE_RATE_GOLD": 0.20,
    "GRACE_RATE_SILVER": 0.10,
    "GRACE_RATE_WATCH": 0.00,
    "MISSED_PENALTY_POINTS": 4,
    "SAME_DAY_HONORED_BONUS": 3,
    "GOLD_SCORE_MIN": 85,
    "SILVER_SCORE_MIN": 70,
    "CONTRACT_ACTIVE_SCORE_MIN": 70,
    "CONTRACT_PROBATION_SCORE_MIN": 50,
    "SEED_SCORE": 100,
}

# Sedation staffing and room capacity (PRD section 3.5).
CAPACITY = {
    "SURGE_ALLOWANCE": 1,
    "SURGE_CUTOFF_HOUR_UTC": 15,
    "RECOVERY_WINDOW_MIN": 90,
    "RECOVERY_BAYS_PER_CASE": 1,
    "DEFAULT_TURNOVER_BUFFER_MIN": 30,
    "DEFAULT_DAILY_CASE_CAP": 6,
    "DEFAULT_RECOVERY_BAY_COUNT": 3,
    "DEFAULT_MAX_CONCURRENT_SEDATION_CASES": 2,
}

# Recovery discharge criteria (PRD section 3.7).
RECOVERY = {
    "MIN_OBSERVATIONS": 2,
    "MIN_ALDRETE_SCORE": 9,
    "MIN_SPAN_MIN": 15,
}

# Maturation readiness (PRD section 3.9).
MATURATION = {
    "MIN_DIAMETER_MM": 6.0,
    "MIN_FLOW_ML_MIN": 600,
    "MAX_DEPTH_MM": 6.0,
    "MIN_DAYS_SINCE_PLACEMENT": 42,
    "MIN_READINGS": 2,
}

# Infection attribution and intervention burden (PRD section 3.9 / 3.7).
BURDEN = {
    "ATTRIBUTION_WINDOW_DAYS": 30,
    "INFECTION_DYSFUNCTION_THRESHOLD": 2,
    "W_ANGIOPLASTY": 2,
    "W_THROMBECTOMY": 3,
    "W_CATHETER_EXCHANGE": 1,
    "W_MATURATION_INTERVENTION": 1,
    "W_ATTRIBUTABLE_INFECTION": 5,
    "CONVERSION_BURDEN_MIN": 4,
}

# Money and the reimbursement ladder (PRD sections 2.9 and 3.8).
MONEY = {
    "PRIMARY_POSITION_PCT": 100,
    "SECONDARY_POSITION_PCT": 50,
    "TERTIARY_POSITION_PCT": 25,
    "M52_FACTOR": 0.50,
    "SESSION_CAP_CENTS": 480000,
    "REBILL_LIMIT": 2,
}

# Referral input bounds (PRD section 3.3).
REFERRAL_LIMITS = {
    "MISSED_TREATMENT_MIN": 0,
    "MISSED_TREATMENT_MAX": 60,
}

# Pagination (PRD section 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Code-family to device-type map used by the billing consistency gate (PRD section 3.8).
CODE_FAMILY_REQUIRED_DEVICE = {
    "ANGIOPLASTY": "BALLOON",
    "THROMBECTOMY": "SHEATH",
    "CATH_EXCHANGE": "SHEATH",
}
