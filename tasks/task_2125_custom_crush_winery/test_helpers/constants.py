"""Domain thresholds and rates named by the PRD."""

# ── Crush-pad yield (PRD 3.3) ────────────────────────────────────────
YIELD = {
    "POUNDS_PER_TON": 2000,
    "BASE_GALLONS_PER_TON": 165.0,
    "HIGH_BRIX_THRESHOLD": 25.00,
    "HIGH_BRIX_FLAT_PENALTY": 5.0,
    "HIGH_BRIX_PER_DEGREE_PENALTY": 2.5,
    "LOW_BRIX_THRESHOLD": 22.00,
    "LOW_BRIX_BONUS": 3.0,
    "BRIX_MIN": 10.00,
    "BRIX_MAX": 35.00,
    "PH_MIN": 2.50,
    "PH_MAX": 4.50,
}

# ── Marginal crush-fee tonnage bands (PRD 3.3) ───────────────────────
CRUSH_TIERS = {
    "TIER1_UPPER_TONS": 25,
    "TIER2_UPPER_TONS": 75,
    "TIER1_MULTIPLIER": 1.0,
    "TIER2_MULTIPLIER": 0.9,
    "TIER3_MULTIPLIER": 0.8,
}

# ── Label eligibility shares (PRD 3.4 / 3.5) ─────────────────────────
LABEL = {
    "VARIETAL_MIN_PCT": 75.00,
    "APPELLATION_MIN_PCT": 85.00,
    "VARIETAL_FALLBACK": "RED_BLEND",
    "APPELLATION_FALLBACK": "CALIFORNIA",
}

# ── Alcohol from sugar (PRD 3.4) ─────────────────────────────────────
ALCOHOL_FROM_BRIX_FACTOR = 0.55

# ── Work-order billing (PRD 3.6) ─────────────────────────────────────
BILLING = {
    "RUSH_SURCHARGE_PCT": 25,
    "DISCOUNT_TIER1_CENTS": 1_000_000,
    "DISCOUNT_TIER1_PCT": 5,
    "DISCOUNT_TIER2_CENTS": 3_000_000,
    "DISCOUNT_TIER2_PCT": 10,
}

# ── Storage accrual (PRD 3.6) ────────────────────────────────────────
STORAGE = {
    "DAYS_PER_MONTH": 30,
    "SECONDS_PER_DAY": 86400,
}

# ── Cooperage occupancy (PRD 3.2) ────────────────────────────────────
VESSEL_CLEANING_BUFFER_HOURS = 48

# ── Bottling (PRD 3.7) ───────────────────────────────────────────────
BOTTLES_PER_CASE = {375: 24, 750: 12, 1500: 6}
ML_PER_GALLON = 3785.411784
RUN_HOUR_QUANTUM = 0.25
LABELS_PER_BOTTLE = 2
DEFAULT_DAILY_CAPACITY_HOURS = 16

# ── Federal excise tax bands (PRD 3.8) ───────────────────────────────
EXCISE_TIERS = {
    "TIER1_UPPER_GALLONS": 30_000,
    "TIER1_CENTS_PER_GALLON": 7,
    "TIER2_UPPER_GALLONS": 130_000,
    "TIER2_CENTS_PER_GALLON": 17,
    "TIER3_CENTS_PER_GALLON": 107,
}

# ── Pagination (PRD 2.3) ─────────────────────────────────────────────
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# ── Clock (PRD 2.4) ──────────────────────────────────────────────────
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_MS = "2026-08-01T00:00:00.000Z"

# ── Values reused by the scenarios below ─────────────────────────────
TEST_DEFAULTS = {
    "HARVEST_YEAR": 2026,
    "COMMITTED_TONS": 200,
    "TANK_GALLONS_ENTITLED": 20000,
    "BARREL_SLOTS_ENTITLED": 40,
    "CRUSH_RATE_CENTS_PER_TON": 50000,
    "STORAGE_RATE_CENTS_PER_GALLON_MONTH": 25,
    "LABOR_RATE_CENTS_PER_HOUR": 10000,
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-07-31T00:00:00Z",
}
