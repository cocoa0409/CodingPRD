"""Domain thresholds and test defaults taken from the PRD's stated constants."""

# --- Numeric constants named in PRD prose ----------------------------------
THRESHOLDS = {
    # surge escalation brackets (basis points; 10000 == 1.0x)
    "SURGE_BASE_BP": 10000,
    "SURGE_STEP_30_BP": 17500,
    "SURGE_STEP_60_BP": 15000,
    "SURGE_STEP_120_BP": 12500,
    "SURGE_120_MIN_BOUNDARY": 120,
    # tier bonus rates (basis points)
    "TIER_BONUS_BP_STANDARD": 0,
    "TIER_BONUS_BP_PLUS": 500,
    "TIER_BONUS_BP_PREMIER": 1000,
    # package money rules (integer cents)
    "SURCHARGE_PER_KG_CENTS": 155,
    "LATE_PENALTY_CENTS": 200,
    "PHOTO_PENALTY_CENTS": 150,
    "FAILED_PENALTY_CENTS": 500,
    # completion rating points
    "RATING_PERFECT_POINTS": 500,
    "RATING_LATE_DEDUCTION": 100,
    "RATING_PHOTO_DEDUCTION": 50,
    "RATING_RETURNED_DEDUCTION": 200,
    "RATING_FLOOR_POINTS": 100,
    # tier qualification thresholds (inclusive)
    "PREMIER_RATING_X100": 470,
    "PREMIER_RELIABILITY_BP": 9500,
    "PLUS_RATING_X100": 430,
    "PLUS_RELIABILITY_BP": 8500,
    # reliability strikes
    "RELIABILITY_START_BP": 10000,
    "FORFEIT_STRIKE_BP": 500,
    "NO_SHOW_STRIKE_BP": 1000,
    # check-in window (minutes around starts_at)
    "CHECKIN_EARLY_MINUTES": 30,
    "CHECKIN_GRACE_MINUTES": 15,
    # reserved-offer buffer gap (minutes)
    "OFFER_BUFFER_MINUTES": 30,
}

# --- Shared payload defaults ------------------------------------------------
TEST_DEFAULTS = {
    "STATION_NAME": "Station A",
    "ZONE_CODE": "SEA1",
    "DRIVER_NAME": "Dana One",
    "DRIVER_EMAIL": "dana.one@example.com",
    "DRIVER2_NAME": "Eve Two",
    "DRIVER2_EMAIL": "eve.two@example.com",
    "VIN": "VIN-D1-0001",
    "VIN2": "VIN-E2-0002",
    "VIN_VAN": "VIN-D1-VAN2",
    "VEHICLE_CLASS": "SEDAN",
    "INSURANCE_LONG": "2027-01-01",
    "BASE_PAY_CENTS": 4000,
    "PHOTO_URL": "https://img.example/pw1.jpg",
    "OFFER_EXPIRES": "2026-09-03T00:00:00Z",
}

# The logical clock's documented startup instant.
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"
