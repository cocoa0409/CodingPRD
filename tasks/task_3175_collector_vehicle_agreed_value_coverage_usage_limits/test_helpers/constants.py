"""Domain thresholds — numeric constants from the PRD's calculations."""

# Logical clock initial reading (PRD section on the logical clock).
CLOCK_INITIAL_ISO = "2026-09-01T00:00:00Z"

# Vehicle eligibility age minimums per class.
AGE_MINIMUMS = {
    "ANTIQUE": 45,
    "CLASSIC": 25,
    "MODERN_COLLECTIBLE": 15,
    "EXOTIC": 10,
}

# The eight required photo types of the photographic dossier.
REQUIRED_PHOTO_TYPES = [
    "FRONT",
    "REAR",
    "DRIVER_SIDE",
    "PASSENGER_SIDE",
    "INTERIOR",
    "ENGINE",
    "ODOMETER",
    "VIN_PLATE",
]

# Guide-tool condition multipliers.
CONDITION_MULTIPLIERS = {
    "EXCELLENT": 1.25,
    "GOOD": 1.00,
    "FAIR": 0.75,
    "PROJECT": 0.50,
}

# Auction-composite constants.
COMPS_WINDOW_DAYS = 730
COMPS_MIN = 3
COMPS_MAX = 5

# Premium rating constants (integer cents).
TIER1_CAP_CENTS = 5_000_000
TIER1_RATE = 0.009
TIER2_CAP_CENTS = 15_000_000
TIER2_RATE = 0.007
TIER3_RATE = 0.0055
USAGE_MULT = {"LIMITED": 0.85, "REGULAR": 1.00, "EXTENDED": 1.20}
STORAGE_MULT = {"ENCLOSED_GARAGE": 0.95, "CARPORT": 1.00}
CLUB_MULT = {"CONCOURS": 0.90, "ENTHUSIAST": 0.95, "BASIC": 1.00}
ENDORSEMENT_FEE_RATE = 0.01

# Mileage ledger constants.
OVERAGE_RATE_CENTS_PER_MILE = 12.5
HARD_CAP_FACTOR = 1.5
DEFAULT_ANNUAL_MILEAGE_ALLOWANCE = 3000

# Restoration stage caps (fractions of agreed value).
STAGE_CAP = {
    "DISASSEMBLY": 0.10,
    "BODYWORK": 0.25,
    "MECHANICAL": 0.40,
    "FINISH": 0.55,
}

# Roadside per-tier annual call limits.
ROADSIDE_LIMITS = {"BASIC": 2, "ENTHUSIAST": 4, "CONCOURS": 6}

# Repair-authorization estimate ceiling (fraction of coverage limit).
REPAIR_ESTIMATE_MAX_FRACTION = 0.75

# Valuation staleness age in days.
VALUATION_STALE_DAYS = 365

# Policy lapse reinstatement grace in days.
LAPSE_GRACE_DAYS = 30

# Sanity band fraction for valuation approval.
SANITY_BAND_FRACTION = 0.20

TEST_DEFAULTS = {
    "GUIDE_BASE_VALUE_CENTS": 3_000_000,
    "GUIDE_YEAR_MIN": 1965,
    "GUIDE_YEAR_MAX": 1972,
    "VEHICLE_YEAR": 1970,
    "VEHICLE_MAKE": "Ford",
    "VEHICLE_MODEL": "Mustang",
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2027-09-01T00:00:00Z",
    "GUIDE_EDITION": "2026-Q3",
    "GUIDE_EFFECTIVE_DATE": "2026-09-01T00:00:00Z",
}
