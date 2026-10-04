"""Domain thresholds and defaults named by the PRD's calculation rules."""

THRESHOLDS = {
    # Corridor readiness scoring (§2.6)
    "PASS_WEIGHT": 60,
    "PENDING_WEIGHT": 20,
    "VARIANCE_TOLERANCE_MS": 150,
    "VARIANCE_CAP": 40,
    # Committed-rate / safety-tier bands (§3.2, §3.6)
    "HIGH_TIER_THRESHOLD": 800,
    "MEDIUM_TIER_THRESHOLD": 500,
    "DISCOUNT_HIGH": 0,
    "DISCOUNT_MEDIUM": 15,
    "DISCOUNT_LOW": 40,
    # Carrier rate reconciliation (§3.11)
    "COMMISSION_BPS": 125,
    # Scenario rate estimate (§3.11)
    "COVERAGE_MONTHS": 1,
    "WEATHER_ADJUSTMENT_CENTS": 8,
    # Transfer turnaround index (§2.7)
    "ROUNDTRIP_FACTOR": 0.5,
    "TURNAROUND_EMPTY_DEFAULT": 0,
    # Safe-stop fee bands → §2.6 exposure health factors and §3.4 bands
    "SAFE_STOP_LOW_BAND_LIMIT": 1000,
    "SAFE_STOP_HIGH_BAND_LIMIT": 5000,
    "SAFE_STOP_FEE_MID": 25000,
    "SAFE_STOP_FEE_HIGH": 60000,
    "HEALTH_CLEAN": 1.0,
    "HEALTH_WATCH": 1.5,
    "HEALTH_SUSPENDED": 2.0,
    "TRANSIT_MINUTES_PER_MILE": 1.6,
    # Incident bands (§3.6)
    "INCIDENT_WATCH_THRESHOLD": 2,
    "INCIDENT_SUSPENDED_THRESHOLD": 5,
    # Driver reroute risk (§3.8)
    "DRIVER_WEIGHT": 0.5,
    "CREDENTIAL_EVENT_PENALTY": 50,
    "RISK_FLOOR": 0,
    # Run-plan exposure (§3.11)
    "LATE_RATE": 0.0105,
    "WEATHER_ATTRIBUTION_CENTS": 8.037,
    # Launch gate ceilings (§3.1)
    "WEATHER_CEILING": 80,
    "WEATHER_OPEN_LIMIT": 40,
    "LOAD_SECUREMENT_MIN_LBS": 40000,
    "VGM_MIN_KG": 100,
    # Carrier lifecycle (§3.6)
    "CARRIER_START_SCORE": 900,
    "CARRIER_ONBOARDING_SCORE": 500,
    "SAFETY_SCORE_PER_INCIDENT": 25,
    # Ride-along credit (§3.2)
    "RIDE_ALONG_CREDIT_BASE": 1200.00,
}

TEST_DEFAULTS = {
    "EPOCH_START": "2026-09-01T00:00:00Z",
    "EPOCH_END": "2026-10-01T00:00:00Z",
    "HOURS_PER_EPOCH": 24,
    "APRON_CAPACITY": 40,
    "HIGHWAY_SEGMENT_MILES": 120,
    "SHIPPER_FLOOR_PER_MILE_CENTS": 100,
    "COMMITTED_SLOTS": 5,
    "POSTED_PER_MILE_CENTS": 225,
    "TRAILER_COUNT": 2,
    "CARRIER_START_SCORE": 900,
}