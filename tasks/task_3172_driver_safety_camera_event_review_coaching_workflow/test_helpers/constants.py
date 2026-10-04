"""Domain thresholds — numeric constants from the PRD calculations."""

THRESHOLDS = {
    # Rolling escalation window length in days (PRD Section 3.7).
    "ESCALATION_WINDOW_DAYS": 90,
    # Escalation triggers when the confirmed count crosses from exactly 2
    # to 3 or more (PRD Section 3.7).
    "ESCALATION_TRIGGER_COUNT": 3,
    # Exoneration window after confirmation, in days (PRD Section 3.8).
    "EXONERATION_WINDOW_DAYS": 30,
    # Score age-factor boundary, in days (PRD Section 3.9).
    "AGE_FACTOR_FRESH_DAYS": 30,
    "AGE_FACTOR_AGED_DAYS": 90,
    # Per-event penalty multiplier (PRD Section 3.9).
    "PENALTY_FACTOR": 2.5,
    # Fresh / aged age factors (PRD Section 3.9).
    "AGE_FACTOR_FRESH": 1.00,
    "AGE_FACTOR_AGED": 0.33,
    # Collision upload-priority boost (PRD Section 3.3).
    "COLLISION_PRIORITY_BOOST": 1000,
    # Auto-created coaching session length in days (PRD Section 3.4).
    "AUTO_SESSION_LENGTH_DAYS": 7,
    # Default logical clock value (PRD Section 2.5).
    "CLOCK_DEFAULT_ISO": "2026-09-01T00:00:00Z",
}

SEVERITY_WEIGHTS = {
    "LOW": 1,
    "MEDIUM": 3,
    "HIGH": 6,
    "CRITICAL": 10,
}

BANDWIDTH_TIER_MULTIPLIERS = {
    "LOW": 1,
    "STANDARD": 2,
    "HIGH": 3,
}

# Incentive pricing table (PRD Section 3.9): inclusive thresholds.
INCENTIVE_TIERS = {
    "GOLD": {"min_score": 95.00, "amount_cents": 50000},
    "SILVER": {"min_score": 90.00, "amount_cents": 25000},
    "BRONZE": {"min_score": 80.00, "amount_cents": 10000},
    "NONE": {"min_score": 0.00, "amount_cents": 0},
}

TEST_DEFAULTS = {
    "FLEET_NAME": "Blue Ridge Freight",
    "FLEET_BUDGET_CENTS": 1000000,
    "TERMINAL_NAME": "Knoxville Depot",
    "TERMINAL_REGION_CODE": "TN",
    "DRIVER_EMPLOYEE_REF": "E-1001",
    "DRIVER_NAME": "Dana Ruiz",
    "DRIVER_HIRE_DATE": "2024-03-01T00:00:00Z",
    "VEHICLE_VIN": "1HGCM82633A004352",
    "VEHICLE_CAMERA_UNIT_ID": "CAM-77",
    "VEHICLE_BANDWIDTH_TIER": "HIGH",
    "POLICY_NAME": "Standard Policy",
    "POLICY_RETENTION_DAYS_STANDARD": 30,
    "POLICY_RETENTION_DAYS_COLLISION": 180,
    "POLICY_DAILY_UPLOAD_CAP_MB": 100,
    "POLICY_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "REVIEWER_USER_ID": "sm-1",
    "ADJUSTER_USER_ID": "ca-1",
}
