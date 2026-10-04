"""Domain thresholds — the numeric constants the PRD pins, plus shared literals."""

THRESHOLDS = {
    # Route evaluation / modeled street time
    "LETTER_CASING_RATE": 18.0,
    "FLAT_CASING_RATE": 8.0,
    "PULLDOWN_RATE": 70.0,
    "PARCEL_STOP_MINUTES": 2.5,
    "TIER1_THRESHOLD": 6000,
    "TIER2_THRESHOLD": 12000,
    "TIER_FACTORS": [1.00, 0.97, 0.94],
    "EVALUATION_DIVISOR": 6,
    # Route baselines
    "BASE_EVALUATED_MINUTES": 480,
    "PROPOSED_MIN_MINUTES": 240,
    "PROPOSED_MAX_MINUTES": 600,
    # Auxiliary assistance
    "MIN_OVERRUN_MINUTES": 30,
    "SURGE_MULTIPLIER": 1.25,
    "OVERBURDEN_KICKER": 15,
    "MAX_ASSISTANCE_MINUTES": 240,
    # Vacancy
    "VACANCY_DISCONTINUE_THRESHOLD_DAYS": 90,
    # Service standards
    "MAX_SERVICE_DAYS": 7,
    "NON_CONTIGUOUS_CAP": 10,
    # Case geometry
    "LETTERS_PER_LOT_PAIR": 2,
    "FLATS_PER_LOT_TRIPLE": 3,
    # COA / hold / inquiry windows
    "COA_TEMPORARY_MAX_DAYS": 364,
    "HOLD_MAX_DAYS": 30,
    "REOPEN_WINDOW_DAYS": 14,
    "INQUIRY_ABANDON_DAYS": 30,
    "ADJUST_MIN_EFFECTIVE_LEAD_DAYS": 7,
    "FULL_COUNT_LEAD_DAYS": 14,
    "DEFAULT_SCAN_COMPLIANCE_TARGET": 0.98,
}

TEST_DEFAULTS = {
    "CASE_SLOT_COUNT": 500,
    "FACILITY_CODE": "LAX",
    "FACILITY_TYPE": "P_AND_DC",
    "REGION_CLASS": "CONTIGUOUS",
    "DISPATCH_CUTOFF": "17:00",
    "OPERATING_DAYS": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
}

# Startup logical clock value pinned by the PRD.
CLOCK_STARTUP = "2026-09-01T00:00:00Z"

SUPERVISOR_USER_ID = "sup-maria"
POSTMASTER_USER_ID = "pm-owens"
