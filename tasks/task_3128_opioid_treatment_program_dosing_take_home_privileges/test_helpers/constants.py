"""Domain thresholds and constants (PRD sections 2.5, 2.7, 2.9, 3.7, 3.9, 3.12, 3.13).

Numeric and table constants that the PRD's calculation rules read.
"""

# --- Stability channels (PRD 2.5) -------------------------------------------
STABILITY_DIRECTION_A = {
    "BASE_SCORE": 50.0,
    "TREATMENT_DAYS_WEIGHT": 0.25,
    "TREATMENT_DAYS_CAP": 25.0,
    "DOSE_COMPLETION_WEIGHT": 2.0,
    "MISSED_STREAK_LINEAR": 3.0,
    "MISSED_STREAK_QUADRATIC": 0.5,
    "DENIAL_WEIGHT": 1.5,
    "COUNSELING_WEIGHT": 1.0,
    "COUNSELING_CAP": 4,
}

STABILITY_DIRECTION_B = {
    "MISSED_STREAK_WEIGHT": 8.0,
    "NO_TRANSPORT_PENALTY": 12.0,
    "CONFIRMED_DIVERSION_PENALTY": 20.0,
    "UNDER_INVESTIGATION_PENALTY": 10.0,
    "COUNSELING_DEFICIENT_PENALTY": 6.0,
    "REVIEW_OVERDUE_PENALTY": 4.0,
    "LOOKBACK_FIRST_ENTRY_MG": 2.0,
    "LOOKBACK_LAST_ENTRY_MG": 1.5,
    "STABILITY_FLOOR_MAINTENANCE": 70.0,
    "STABILITY_FLOOR_OTHER": 75.0,
}

# --- Carry tables (PRD 3.7) -------------------------------------------------
CARRY_TIME_IN_TREATMENT_TABLE = [
    (730, 27),
    (540, 13),
    (365, 6),
    (270, 3),
    (180, 2),
    (90, 1),
]

CARRY_PHASE_TABLE = {
    "INDUCTION": 0,
    "STABILIZATION": 1,
    "MAINTENANCE": 6,
    "MEDICAL_WITHDRAWAL": 0,
}

POOL_DIVISOR = 2.0

# --- Patient risk tier (PRD 3.2) --------------------------------------------
RISK = {
    "TRANSPORT_NO_RELIABLE": 12.0,
    "TRANSPORT_RIDE_SHARE": 5.0,
    "TRANSPORT_PUBLIC_TRANSIT": 1.5,
    "TRANSPORT_PRIVATE_VEHICLE": 0.0,
    "DIVERSION_CONFIRMED": 30.0,
    "DIVERSION_UNDER_INVESTIGATION": 8.0,
    "DENIAL_WEIGHT": 1.0,
    "DENIAL_CAP": 12,
    "MISSED_STREAK_WEIGHT": 2.0,
    "PHASE_DECAY_BASE": 30.0,
    "PHASE_DECAY_RATE": 0.1,
    "HIGH_THRESHOLD": 25.0,
    "MODERATE_THRESHOLD": 12.0,
    "REINSTATEMENT_SURCHARGE": 5.0,
}

# --- Counseling and plan-review cadence (PRD 3.8) ---------------------------
CADENCE = {
    "COUNSELING_REQUIRED_MINUTES": 60.0,
    "PHASE_CADENCE": {
        "INDUCTION": 7,
        "STABILIZATION": 14,
        "MAINTENANCE": 30,
        "MEDICAL_WITHDRAWAL": 7,
    },
    "REVIEW_GRACE_DAYS": 3,
}

# --- Dose tariff (PRD 3.4) --------------------------------------------------
DOSE_TARIFF = {
    "TIER_1_RATE": 2.90,
    "TIER_2_RATE": 3.30,
    "TIER_3_RATE": 5.25,
    "TIER_4_RATE": 6.80,
    "OVER_CEILING_RATE": 1.25,
    "HANDLING_RATE_PER_MG": 0.0125,
    "SECURITY_RATE_PER_MG": 0.0075,
    "WASTE_FEE_PER_10MG": 1.15,
    "WASTE_FREE_ALLOWANCE_MG": 10.0,
}

# --- Inventory variance and write-off (PRD 3.12) ----------------------------
INVENTORY_VARIANCE = {
    "ABSOLUTE_TOLERANCE_MG": 50.0,
    "RELATIVE_TOLERANCE_RATE": 0.02,
    "RESTRICTED_VARIANCE_MG": 500.0,
}

# --- Inspection readiness (PRD 3.13) ----------------------------------------
INSPECTION_READINESS = {
    "BASE_SCORE": 100.0,
    "CRITICAL_FINDING_PENALTY": 12.0,
    "MAJOR_FINDING_PENALTY": 6.0,
    "MINOR_FINDING_PENALTY": 2.0,
    "OPEN_DIVERSION_PENALTY": 10.0,
    "VARIANCE_PENALTY": 15.0,
    "COUNSELING_BREACH_PENALTY": 20.0,
    "LAPSED_PRIVILEGE_PENALTY": 10.0,
    "READY_THRESHOLD": 85.0,
    "NEEDS_ATTENTION_THRESHOLD": 60.0,
}

# --- Discipline thresholds (PRD 3.3, 3.6, 3.9) ------------------------------
TREATMENT_GATES = {
    "MIN_TIME_IN_TREATMENT_DAYS": 90,
    "MAX_DENIAL_COUNT_12MO": 2,
    "MISSED_STREAK_SUSPENSION": 3,
    "TITRATION_STEP_MG": 10.0,
    "CARRY_INTERVAL_MIN_DAYS": 1,
    "CARRY_INTERVAL_MAX_DAYS": 28,
    "JUSTIFICATION_MIN_CHARS": 40,
    "PLAN_TEXT_MIN_CHARS": 20,
    "OUTCOME_SUMMARY_MIN_CHARS": 20,
    "TRACKING_WINDOW_DAYS": 28,
}

# Combined lookup for convenience.
THRESHOLDS = {
    **STABILITY_DIRECTION_A,
    **{f"DIRECTION_B_{k}": v for k, v in STABILITY_DIRECTION_B.items()},
    "POOL_DIVISOR": POOL_DIVISOR,
    **{f"RISK_{k}": v for k, v in RISK.items()},
    **{f"TARIFF_{k}": v for k, v in DOSE_TARIFF.items()},
    **{f"VARIANCE_{k}": v for k, v in INVENTORY_VARIANCE.items()},
    **{f"READINESS_{k}": v for k, v in INSPECTION_READINESS.items()},
    **TREATMENT_GATES,
}

# Sensible defaults used by factories.
TEST_DEFAULTS = {
    "PROGRAM_NAME": "BayMark Riverside",
    "STATE_CODE": "CA",
    "CLINIC_HOURS_START": "06:00",
    "CLINIC_HOURS_END": "11:00",
    "OPEN_DAYS": ["MO", "TU", "WE", "TH", "FR", "SA"],
    "MAX_DAILY_DOSE_SLOTS": 120,
    "MAX_DAILY_MG_METHADONE": 120.0,
    "MAX_DAILY_MG_BUPRENORPHINE": 24.0,
    "DOSE_CHECKIN_GRACE_MINUTES": 30,
    "ALLOTTED_CARRIES": 10,
    "LOT_QUANTITY_MG": 50000.0,
    "ORDERED_DAILY_MG": 90.0,
    "SERVICE_DATE": "2026-12-21",
    "SERVICE_DATETIME": "2026-12-21T07:00:00Z",
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "CLOCK_ADVANCED": "2026-12-15T00:00:00Z",
    "ADMISSION_DATE": "2026-09-01",
}