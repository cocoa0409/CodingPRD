"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Claim allowed amounts (PRD §3.5)
    "ESTIMATED_RATE": 0.62,
    "CONTRACT_RATE": 0.60,
    # Distance eligibility (PRD §3.7)
    "ROAD_CIRCUITY_FACTOR": 1.3,
    "DISTANCE_THRESHOLD_MILES": 100.0,
    "EARTH_RADIUS_MILES": 3958.8,
    # Travel stipend tiering (PRD §3.7)
    "LODGING_TIER1_CENTS": 15000,
    "LODGING_TIER2_CENTS": 22500,
    "TRAVEL_PER_MILE_CENTS": 58,
    "TRAVEL_CAP_CENTS": 100000,
    # Allocation weight (PRD §3.9)
    "BASE_WEIGHT": 1.0,
    "CAPACITY_STRAIN_FRACTION": 0.5,
    # Screening conversion (PRD §3.8)
    "CONVERSION_WINDOW_DAYS": 90,
    # Clinic conflict (PRD §3.8)
    "LOCATION_RADIUS_MILES": 25.0,
    "BUFFER_DAYS": 7,
    # Committee quorum weights (PRD §3.3)
    "ACCEPT_QUORUM_WEIGHT": 3,
    "DENY_QUORUM_WEIGHT": 2,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "HOSPITAL_LAT": 45.0,
    "HOSPITAL_LON": -122.0,
    "CLINIC_LAT": 45.67,
    "CLINIC_LON": -118.79,
}
