"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Item pallet design (PRD §3.1)
    "STANDARD_SLOT_LENGTH_IN": 48,
    "STANDARD_SLOT_WIDTH_IN": 40,
    # Allocation priority score (PRD §3.3)
    "MEMBER_BASE_CAP": 200000,
    "DEMO_WEIGHT": 0.5,
    "INCOME_CAP_CENTS": 20000000,
    "INCOME_WEIGHT": 0.3,
    "VELOCITY_BASE": 10,
    "WINDOW_DAYS_REGULAR": 7,
    "WINDOW_DAYS_TREASURE_HUNT": 3,
    # Unload fee (PRD §3.2)
    "PER_PALLET_FEE_CENTS": 4500,
    "SMALL_LOAD_THRESHOLD": 10,
    "MID_LOAD_THRESHOLD": 25,
    # Chargeback amounts (PRD §3.6)
    "LATE_CHECKIN_BASE_CENTS": 15000,
    "NO_SHOW_BASE_CENTS": 75000,
    "OVER_PALLET_COUNT_BASE_CENTS": 25000,
    "PER_EXTRA_PALLET_CENTS": 6000,
    "REPEAT_CAP": 4,
    "REPEAT_STEP": 0.25,
    "LATE_GRACE_MINUTES": 15,
    "APPEAL_WINDOW_DAYS": 7,
    # Club posture ladder (PRD §3.4)
    "CONSTRAINED_THRESHOLD_PCT": 80,
    # Complaints / deletion review (PRD §3.7)
    "WEIGHT_SAFETY": 4.0,
    "WEIGHT_QUALITY": 2.0,
    "WEIGHT_AVAILABILITY": 1.5,
    "WEIGHT_PRICING": 1.0,
    "COMPLAINT_WINDOW_DAYS": 30,
    "COMPLAINT_DISCONTINUE_THRESHOLD": 25.0,
    # Vendor compliance (PRD §3.6)
    "COMPLIANCE_SUSPEND_THRESHOLD_BP": 8500,
    "PERFECT_SCORE_BP": 10000,
    "PENALTY_LATE_CHECKIN": 250,
    "PENALTY_NO_SHOW": 600,
    "PENALTY_OVER_PALLET_COUNT": 400,
}

TEST_DEFAULTS = {
    # Standard pallet design used across tests: 24 * 5 * 4 = 480 units, 40x40 in.
    "CASE_PACK_QTY": 24,
    "PALLET_LENGTH_IN": 40,
    "PALLET_WIDTH_IN": 40,
    "CASES_PER_LAYER": 5,
    "MAX_LAYERS": 4,
    "PALLET_QTY_UNITS": 480,
    "CLUB_FLOOR_SLOT_CAPACITY": 40,
    "MEMBER_BASE": 1000,
    "AVG_MEMBER_INCOME_CENTS": 5000000,
    "DOCK_HOURS_OPEN": "09:00",
    "DOCK_HOURS_CLOSE": "17:00",
    "SLOT_LENGTH_MINUTES": 30,
    "CUTOFF_TIME": "16:00",
}
