"""Domain thresholds and constants, each traceable to a PRD sentence.

Nothing here is invented: every literal appears in PRD §2 or §3 prose.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
# "Before any call to the clock-setting capability, the server's logical clock
# reads exactly 2026-09-01T00:00:00Z".
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# --- Flock lifecycle (PRD §3.2) ----------------------------------------------
GROWING_WEEKS = 18            # "eighteen weeks or older lands directly in LAYING"
MOLT_MIN_AGE_WEEKS = 50       # "at least fifty weeks old"
MOLT_DURATION_WEEKS = 4       # "at least four weeks have elapsed since molt_start_age_weeks"
AUTO_DEPLETE_AGE_WEEKS = 80   # "age_weeks has reached eighty weeks"
POST_MOLT_RATE_FACTOR = 0.95  # "the band rate is multiplied by 0.95"
PLACEMENT_MAX_AGE_WEEKS = 30  # "no more than thirty whole weeks past it"
OCCUPANCY_WINDOW_DAYS = 560   # "from placement_date to 560 days later"
WEEKLY_MORTALITY_BPS = 10     # "one-tenth of one percent (ten basis points)"

# --- Certifications (PRD §3.1) -----------------------------------------------
CERT_VALIDITY_DAYS = 365      # "sets valid_until exactly 365 days later"

# --- Settlement pricing (PRD §3.4) -------------------------------------------
# Segment-keyed weekly-spend tiers: (threshold_cents, discount_cents_per_dozen)
VOLUME_TIERS = {
    "RETAIL": [(2_000_000, 4), (500_000, 2)],
    "FOODSERVICE": [(5_000_000, 5), (1_000_000, 2)],
    "PROCESSOR": [(10_000_000, 6), (2_500_000, 3)],
}
SETTLEMENT_WEEK_DAYS = 7

# --- Feed milling (PRD §3.8) --------------------------------------------------
FEED_LBS_PER_DOZEN = 4.0
POUNDS_PER_TON = 2000
STANDARD_CORN_SHARE = 0.60
STANDARD_CORN_CENTS_PER_TON = 18_000
STANDARD_SOY_CENTS_PER_TON = 36_000
# "a constant 25,200 cents per ton ... yielding a constant 50.40 cents per dozen"
STANDARD_BLEND_CENTS_PER_TON = 25_200
STANDARD_COST_PER_DOZEN_CENTS = 50.40

# --- Depopulation downtime (PRD §3.3) -----------------------------------------
DISPOSAL_DOWNTIME_DAYS = {
    "COMPOSTING": 42,
    "BURIAL": 28,
    "INCINERATION": 21,
    "LANDFILL": 35,
}
REGIONAL_DISEASE_BONUS_DAYS = 14
REGIONAL_DISEASE_LOOKBACK_DAYS = 30

# --- Packing (PRD §3.9) --------------------------------------------------------
CASE_DOZEN = 30
SIZE_CLASS_ORDER = ["JUMBO", "EXTRA_LARGE", "LARGE", "MEDIUM", "SMALL", "PEEWEE"]
BAND_DIST = {
    "YOUNG": {"JUMBO": 0.02, "EXTRA_LARGE": 0.12, "LARGE": 0.38,
              "MEDIUM": 0.30, "SMALL": 0.14, "PEEWEE": 0.04},
    "PEAK": {"JUMBO": 0.08, "EXTRA_LARGE": 0.24, "LARGE": 0.42,
             "MEDIUM": 0.18, "SMALL": 0.06, "PEEWEE": 0.02},
    "OLD": {"JUMBO": 0.12, "EXTRA_LARGE": 0.30, "LARGE": 0.36,
            "MEDIUM": 0.14, "SMALL": 0.06, "PEEWEE": 0.02},
}

# --- Cage-free conversion (PRD §3.5) -------------------------------------------
SUPPORT_HENS_PER_WEEKLY_DOZEN = 2

# --- Ship / order windows (PRD §3.6) -------------------------------------------
SHIP_WINDOW_DAYS = 14
ALLOCATE_WINDOW_DAYS = 14

# --- Test data defaults ---------------------------------------------------------
TEST_DEFAULTS = {
    "MILL_RECEIVING_TONS_PER_DAY": 100,
    "BIG_MILL_RECEIVING_TONS_PER_DAY": 1000,
    "HOUSE_CAPACITY": 100_000,
    "CREDIT_LIMIT_CENTS": 500_000_000,
}
