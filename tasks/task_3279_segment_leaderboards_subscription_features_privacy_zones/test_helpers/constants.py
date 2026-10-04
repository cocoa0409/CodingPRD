"""Domain thresholds from the PRD's calculation and rule sections."""

THRESHOLDS = {
    # Speed and vehicle integrity check (PRD section 3.4)
    "MAX_SPEED_RIDE_KMH": 80,
    "MAX_SPEED_RUN_KMH": 30,
    "MAX_SPEED_SWIM_KMH": 10,
    "MAX_SPEED_EBIKE_KMH": 45,
    "MAX_SPEED_VIRTUAL_KMH": 100,
    "ASSIST_FACTOR_RIDE": 0.8,
    "ASSIST_FACTOR_RUN": 0.8,
    "ASSIST_FACTOR_SWIM": 0.8,
    "ASSIST_FACTOR_EBIKE": 0.7,
    "ASSIST_FACTOR_VIRTUAL": 0.9,
    # Segment spatial overlap gate (PRD section 3.5)
    "OVERLAP_EPSILON_M": 50,
    # Virtual event half-open window (PRD section 3.7)
    "EVENT_WINDOW_S": 3600,
    # Heat map cell visibility (PRD section 3.8)
    "MIN_CELL_COUNT": 3,
    # Route load score (PRD section 3.8)
    "PLAN_LOAD_DIVISOR": 1000,
    "PLAN_ACTIVITY_DIVISOR": 2000,
    "CAP_RATIO": 1.5,
    "CAP_BONUS": 25,
    # Free-tier weekly route cap (PRD sections 2.9 and 3.8)
    "FREE_WEEKLY_ROUTE_CAP": 3,
    # Free-tier leaderboard row cap (PRD section 2.9)
    "FREE_LEADERBOARD_ROW_CAP": 10,
    # Safety score arithmetic (PRD section 3.6)
    "SAFETY_SCORE_START": 100,
    "SAFETY_SCORE_UPHOLD_PENALTY": 10,
    "SAFETY_SCORE_REJECT_BONUS": 5,
    "SAFETY_SCORE_AUTOHIDE_BELOW": 50,
    # Duplicate detection windows (PRD section 3.4)
    "DUPLICATE_START_WINDOW_S": 120,
    "DUPLICATE_DISTANCE_TOLERANCE": 0.05,
    # Privacy zone geometry bounds (PRD section 3.3)
    "ZONE_RADIUS_MIN_M": 200,
    "ZONE_RADIUS_MAX_M": 2000,
    # Logical clock startup default (PRD section 2.6)
    "CLOCK_DEFAULT_ISO": "2026-09-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "HOME_LAT": 37.0,
    "HOME_LNG": -122.0,
}
