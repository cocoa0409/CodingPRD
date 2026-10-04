"""Domain thresholds and defaults — numeric constants from the PRD."""

THRESHOLDS = {
    # Renewal fee construction (cents).
    "BASE_FEE_CENTS": 50000,
    "PER_TEAM_FEE_CENTS": 7500,
    "LATE_MULTIPLIER": 1.175,
    # Participation percentage threshold; exactly 60.00 passes.
    "PARTICIPATION_THRESHOLD": 60.00,
    # Roster size window (benchmark scale for the real 12..14).
    "MIN_ROSTER_SIZE": 3,
    "MAX_ROSTER_SIZE": 5,
    # Pitch maxima by division code.
    "PITCH_MAX_TEE_BALL": 50,
    "PITCH_MAX_MINOR": 75,
    "PITCH_MAX_MAJOR": 85,
    "PITCH_MAX_JUNIOR": 95,
    "PITCH_MAX_SENIOR": 95,
    # Rest tiers (closed intervals, inclusive ceilings).
    "REST_TIER_1_MAX": 20,   # 1..20   -> 0 days
    "REST_TIER_2_MAX": 35,   # 21..35  -> 1 day
    "REST_TIER_3_MAX": 50,   # 36..50  -> 2 days
    "REST_TIER_4_MAX": 65,   # 51..65  -> 3 days
    # 66..cap -> 4 days
    # Elimination limits.
    "SINGLE_ELIMINATION_LIMIT": 1,
    "DOUBLE_ELIMINATION_LIMIT": 2,
    # Document freshness (days).
    "DOCUMENT_FRESHNESS_DAYS": 365,
}

TEST_DEFAULTS = {
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    "ON_TIME_CLOCK": "2026-10-15T00:00:00Z",
    "REGISTRATION_CLOCK": "2027-02-01T00:00:00Z",
    "GAME_CLOCK": "2027-06-01T00:00:00Z",
    "SEASON_YEAR": 2027,
    # Birth dates producing MAJOR (league_age 12) players in season 2027.
    "MAJOR_BIRTH_DATES": [
        "2015-03-10", "2015-04-11", "2015-05-12", "2015-06-13",
        "2015-07-14", "2015-08-15",
    ],
    # Birth certificate issue dates paired with MAJOR_BIRTH_DATES.
    "BIRTH_CERT_ISSUED_DATES": [
        "2015-03-12", "2015-04-12", "2015-05-13", "2015-06-14",
        "2015-07-15", "2015-08-16",
    ],
    "FRESH_DOC_ISSUED": "2027-01-15",
    "INSURANCE_COVERAGE_START": "2027-01-01",
    "INSURANCE_COVERAGE_END": "2027-12-31",
}
