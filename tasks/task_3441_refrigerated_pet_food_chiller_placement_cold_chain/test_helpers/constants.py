"""Domain thresholds — numeric constants pinned by the PRD (§2.4, §2.9-§2.12, §3)."""

# --- Logical clock (PRD §2.4) ---
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Cold-chain temperature governance (PRD §2.10) ---
CHILLER_TEMP_MIN_C = 0.0            # inclusive safe-band lower bound
CHILLER_TEMP_MAX_C = 4.0            # inclusive safe-band upper bound
EXCURSION_SEVERE_MINUTES = 120      # severe threshold, boundary inclusive
SENSOR_TEMP_MIN_C = -40.0           # sensor-plausible range, inclusive
SENSOR_TEMP_MAX_C = 60.0
READING_DURATION_MIN_MINUTES = 1
READING_DURATION_MAX_MINUTES = 1440

# --- Shelf life / removal (PRD §3.7) ---
SHELF_LIFE_DAYS = 45
REMOVAL_LEAD_DAYS = 7
MAX_TRANSIT_HOURS = 48              # boundary inclusive

# --- Site selection score (PRD §3.1) ---
FOOTPRINT_REFERENCE_SQFT = 32
W_D_DEMOGRAPHIC_LED = 0.45
W_V_DEMOGRAPHIC_LED = 0.25
W_F_DEMOGRAPHIC_LED = 0.20
W_C_DEMOGRAPHIC_LED = 0.10
W_D_VELOCITY_LED = 0.20
W_V_VELOCITY_LED = 0.55
W_F_VELOCITY_LED = 0.15
W_C_VELOCITY_LED = 0.10
SCORE_ELIGIBILITY_MIN = 60.0        # inclusive

# --- Installation quote (PRD §3.1) ---
CHILLER_STANDARD_UNIT_CENTS = 325000
CHILLER_COMPACT_UNIT_CENTS = 218000
INSTALL_FEE_CENTS = 45000
RATE_PER_SQFT_CENTS = 1250
RATE_PER_MILE_CENTS = 925

# --- Payback estimate (PRD §3.1, §3.6) ---
UNIT_MARGIN_CENTS = 180
WEEKS_PER_MONTH_NUM = 13
WEEKS_PER_MONTH_DEN = 3
PAYBACK_MAX_MONTHS = 36.0           # inclusive eligibility bound

# --- Chiller model economics (PRD §3.3) ---
STANDARD_CAPACITY_UNITS = 240
COMPACT_CAPACITY_UNITS = 120
STANDARD_FOOTPRINT_SQFT = 8
COMPACT_FOOTPRINT_SQFT = 5

# --- Delivery frequency plan (PRD §3.6) ---
SAFETY_STOCK_FACTOR = 1.25
DELIVERY_TIER_5_MIN = 300           # 5/week at >= 300
DELIVERY_TIER_3_MIN = 150           # 3/week at >= 150
DELIVERY_TIER_2_MIN = 60            # 2/week at >= 60
DELIVERY_TIER_1_MIN = 25            # 1/week at >= 25; below 25 -> 0

# --- Underperformance tracking (PRD §3.6) ---
VELOCITY_FLOOR_UNITS_PER_WEEK = 40  # boundary inclusive
UNDERPERFORMING_STREAK_REMOVAL_MIN = 2

# --- Manufacturing capacity ledger (PRD §2.12) ---
BASE_MANUFACTURING_CAPACITY_UNITS = 200

# --- Evaluation staleness (PRD §3.4) ---
EVALUATION_STALENESS_DAYS = 90

# --- Trial campaigns (PRD §3.8) ---
TRIAL_MIN_GAP_DAYS = 14             # gap boundary inclusive (exactly 14 allowed)

# --- Capacity project terms (PRD §3.2) ---
AGREEMENT_TERM_MONTHS_MIN = 1
AGREEMENT_TERM_MONTHS_MAX = 120

# --- Cascade-minted ticket text (PRD §3.5) ---
AUTO_EXCURSION_ISSUE_SUMMARY = "AUTO: severe temperature excursion"

# --- Worked-fixture expected values, derived from the PRD formulas above ---
# Store Alpha: STANDARD chiller, allocated_sqft 16, distance 10 miles:
# 325000 + 45000 + round(16*1250) + round(10*925) = 399250
STORE_ALPHA_STANDARD_QUOTE_CENTS = 399250
# Store Beta: COMPACT, allocated_sqft 14, distance 12:
# 218000 + 45000 + round(14*1250) + round(12*925) = 291600
STORE_BETA_COMPACT_QUOTE_CENTS = 291600
# Store Delta: COMPACT, allocated_sqft 10, distance 7:
# 218000 + 45000 + round(10*1250) + round(7*925) = 281975
STORE_DELTA_COMPACT_QUOTE_CENTS = 281975
# Store Gamma: STANDARD, allocated_sqft 16, distance 20:
# 325000 + 45000 + 20000 + round(20*925) = 408500
STORE_GAMMA_STANDARD_QUOTE_CENTS = 408500
