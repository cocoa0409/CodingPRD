"""Domain thresholds and constants from PRD sections 2-3."""

CLOCK_START = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Contractor tier thresholds (inclusive, integer cents; PRD section 3.6).
    "SILVER_MIN_CENTS": 1_000_000,
    "GOLD_MIN_CENTS": 4_000_000,
    "PLATINUM_MIN_CENTS": 10_000_000,
    # Tier discounts (PRD section 3.6).
    "SILVER_DISCOUNT": 0.05,
    "GOLD_DISCOUNT": 0.10,
    "PLATINUM_DISCOUNT": 0.15,
    # License term (PRD section 3.3).
    "LICENSE_TERM_DAYS": 365,
    # Attestation freshness window in days (PRD section 3.2).
    "ATTESTATION_FRESH_DAYS": 366,
    # Co-op claim activity window in days (PRD section 3.5).
    "ACTIVITY_WINDOW_DAYS": 90,
    # Calibration validity in days (PRD section 3.3).
    "CALIBRATION_VALID_DAYS": 90,
    # Rolling window in full calendar months (PRD section 2.6).
    "WINDOW_MONTHS": 12,
    # Haversine earth radius in miles (PRD section 3.2).
    "EARTH_RADIUS_MILES": 3958.8,
}

TEST_DEFAULTS = {
    # Standard colorant system used across fixtures.
    "SYSTEM_CODE": "G25",
    "SYSTEM_NAME": "Gen-25 Colorant System",
    "SYSTEM_GENERATION": 25,
    "ANNUAL_LICENSE_FEE_CENTS": 2_500_000,
    "MIN_INITIAL_INVENTORY_UNITS": 40,
    # Standard region.
    "REGION_CODE": "NE",
    "REGION_NAME": "Northeast",
    "TERRITORY_RADIUS_MILES": 25,
    "EXCLUSIVITY_BLOCK_THRESHOLD_PCT": 15,
    # Standard dealer.
    "DEALER_LEGAL_NAME": "Beacon Paint Co",
    "DEALER_LAT": 42.0,
    "DEALER_LON": -71.0,
    "ATTESTED_ON": "2026-08-01T00:00:00Z",
    "COOP_ACCRUAL_RATE": 0.02,
    # Standard specialty line at 100 cents.
    "LINE_CODE": "S1",
    "LINE_NAME": "Specialty One",
    "BASE_PRICE_CENTS": 100,
    # Standard equipment unit.
    "SERIAL_NO": "SN-100",
    "MODEL": "Corob D600",
    # Standard contractor.
    "CONTRACTOR_NAME": "Ace Painting LLC",
}
