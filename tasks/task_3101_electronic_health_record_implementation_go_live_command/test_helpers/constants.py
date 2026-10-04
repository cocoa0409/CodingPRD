"""Domain thresholds and test defaults taken from the PRD's stated constants."""

# --- Numeric floors and ceilings named in PRD prose -------------------------
THRESHOLDS = {
    # readiness posture banding
    "OPEN_POSTURE_MIN": 60.00,
    "RESTRICTED_POSTURE_MIN": 40.00,
    "CUTOVER_READY_SCORE": 85.00,
    # readiness scoring penalties
    "SEV1_PENALTY": 40,
    "SEV2_PENALTY": 25,
    "SEV3_PENALTY": 10,
    "SEV4_PENALTY": 3,
    "INTERCHANNEL_PENALTY": 15,
    "INTERCHANNEL_REJECT_THRESHOLD": 25,
    "OPTIMISTIC_REJECTED_CAP": 5,
    # customization risk
    "LOCAL_CUSTOM_RISK_LIMIT": 40.00,
    "UNIT_CAP": 12,
    "DEPTH_STEP": 0.15,
    "MAX_REJECTIONS": 3,
    # conversion variance caps by payload class
    "PATIENT_DEMOGRAPHICS_MAX_PCT": 1.00,
    "APPOINTMENTS_MAX_PCT": 1.50,
    "ORDERS_MAX_PCT": 2.00,
    "BALANCES_MAX_PCT": 0.50,
    # training
    "CERT_MIN_HOURS": 40,
    "PASSING_SCORE": 80,
    "PROFICIENCY_GATE_PCT": 80.00,
    "CERTIFICATION_VALIDITY_DAYS": 365,
    # interfaces
    "MIN_PASS_RATE": 95.00,
    # revenue cycle
    "STABILIZATION_TARGET": 80.00,
    # cutover / command center
    "HANDOFF_BUFFER_MINUTES": 30,
    "BASE_SLA_MINUTES": 60,
    # optimization
    "EPOCH_CAPACITY_POINTS": 30,
    "MIN_RECONCILED_ORDER_COUNT": 350,
    # test cycles per scenario class
    "UNIT_MIN_CYCLES": 3,
    "INTEGRATED_MIN_CYCLES": 2,
    "CHARGE_CAPTURE_MIN_CYCLES": 1,
}

# Severity penalty lookup, exposed for readability in tests.
SEVERITY_PENALTY = {"SEV1": 40, "SEV2": 25, "SEV3": 10, "SEV4": 3}

# Classification weight lookup for the customization-risk formula.
CLASSIFICATION_WEIGHT = {
    "FOUNDATION_ADOPTED": 1.0,
    "FOUNDATION_ADAPTED": 1.5,
    "LOCAL_CUSTOM": 2.0,
}

# Charge-capture line rates by order type.
CHARGE_LINE_RATES = {
    "LAB": [("PROCESSING", 0.050)],
    "IMAGING": [("TECH", 0.125), ("CONTRAST", 0.075)],
    "MEDICATION": [("DISPENSING", 0.030)],
    "PROCEDURE": [("OR", 0.200), ("ANESTHESIA", 0.050)],
}

# Command-center SLA weights.
SEVERITY_SLA_WEIGHT = {"SEV1": 0.25, "SEV2": 0.50, "SEV3": 1.00, "SEV4": 2.00}
ZONE_MODIFIER = {
    "ED": 0.80,
    "OR": 0.70,
    "ICU": 0.75,
    "MED_SURG": 1.00,
    "RADIOLOGY": 1.10,
    "PHARMACY": 1.05,
}
UNCOVERED_MODIFIER = 0.50

# --- Values tests use for setup ---------------------------------------------
TEST_DEFAULTS = {
    "PROGRAM_NAME": "Northline Health EHR",
    "VENDOR_RELEASE": "2026.2",
    "GO_LIVE_TARGET_UTC": "2026-12-01T00:00:00Z",
    "FACILITY_NAME": "Northline Memorial",
    "FACILITY_TYPE": "ACUTE_CARE",
    "BED_COUNT": 240,
    "ROLLOUT_WAVE": 1,
    "CONVERSION_SCOPE": "FULL_RECORD",
    "DEPARTMENT_CODE": "LAB",
    "APPLICATION_SCOPE": ["LAB", "REPORTS"],
    "REQUIRED_STAFF_COUNT": 10,
    "APPLICATION_CODE": "LAB",
    "BUILD_CLASSIFICATION": "LOCAL_CUSTOM",
    "CUSTOMIZATION_DEPTH": 3,
    "LOCAL_CUSTOM_FIELDS": ["F1", "F2", "F3"],
    "SCENARIO_CLASS": "UNIT",
    "STEP_COUNT": 8,
    "DUE_UTC": "2026-10-01T00:00:00Z",
}

# The logical clock's startup default, restated whenever a test must pin it.
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"