"""Domain thresholds — numeric constants from PRD calculations and rules.

Every value below appears verbatim in PRD.md (the section is noted on each
line); no value is taken from anywhere else.
"""

# --- Logical clock (PRD §2.4) ---
DEFAULT_CLOCK_START_ISO = "2026-09-01T00:00:00Z"  # §2.4 "reads exactly 2026-09-01T00:00:00Z"

# --- Negotiation (PRD §3.1) ---
MAX_NEGOTIATION_ROUNDS = 6          # §3.1 "capped at a round budget of 6"
GROWTH_TARGET_MIN_PCT = -20         # §3.1 "from -20 percent to 50 percent, both bounds inclusive"
GROWTH_TARGET_MAX_PCT = 50          # §3.1 same sentence
FISCAL_YEAR_MIN = 2026              # §3.1 "an integer from 2026 through 2030 inclusive"
FISCAL_YEAR_MAX = 2030              # §3.1 same sentence

# --- Activation / trade fund split (PRD §3.1) ---
FUND_ACCRUAL_RATE_MAX_PCT = 5       # §3.1 "greater than 0 and at most 5"
EVENT_SPLIT_MIN_PCT = 20            # §3.1 "the event bucket must receive at least 20 percent"
EDLP_SPLIT_MAX_PCT = 80             # §3.1 "an integer from 0 to 80 inclusive"

# --- Fund accrual calculation (PRD §3.6) ---
CASH_COLLECTION_FACTOR = 0.92       # §3.6 "multiplied by the collection factor 0.92"

# --- Promotional events (PRD §3.2) ---
PROMO_DISCOUNT_DEPTH_MAX_PCT = 40   # §3.2 "greater than 0 and at most 40"

# --- Shelf recommendations (PRD §3.4) ---
SHELF_SPACE_CHANGE_MAX_PCT = 30     # §3.4 "whose absolute value may not exceed 30 percent"
SHELF_TARGET_STORE_COUNT_MAX = 10000  # §3.4 "an integer from 1 to 10000"
IMPLEMENTATION_SLA_DAYS = 90        # §3.4 "the manufacturer has 90 days from accepted_at"

# --- Price-pack channel conflict (PRD §3.8) ---
CHANNEL_PRICE_GAP_MAX_PCT = 15      # §3.8 "must be at most 15 percent — a gap of exactly 15 percent passes"
ECOMMERCE_UNDERCUT_MAX_PCT = 10     # §3.8 "reduced by 10 percent and rounded up to the next whole cent"
CLUB_PACK_MIN_UNITS = 12            # §3.8 "whose unit_count falls below 12 is rejected"

# --- Launches and reviews (PRD §3.5, §3.9) ---
LAUNCH_MIN_GAP_DAYS = 84            # §3.5 "must sit at least 84 days away"
REVIEW_MIN_DAYS_AFTER_LAUNCH = 84   # §3.9 "the launch's launch_date plus 84 days"
PHASE_COUNT = 4                     # §3.5 "exactly four LaunchPhase children appear", "phase_index 1 through 4"
DISTRIBUTION_SUM_MAX_PCT = 100      # §3.5 "must not exceed 100 percent"

# --- Distribution projection weights (PRD §3.5) ---
PHASE_WEIGHT_GATE_PASSED = 1.0      # §3.5 "a weight of 1.0 for GATE_PASSED"
PHASE_WEIGHT_PENDING = 0.25         # §3.5 "0.25 for PENDING"
PHASE_WEIGHT_GATE_FAILED = 0.0      # §3.5 "0.0 for GATE_FAILED"

# --- Delisting risk score (PRD §3.9) ---
RISK_WEIGHT_SALES = 0.40            # §3.9 "weighs these at 0.40 for sales"
RISK_WEIGHT_DISTRIBUTION = 0.30     # §3.9 "0.30 for distribution"
RISK_WEIGHT_FORECAST = 0.20         # §3.9 "0.20 for forecast bias"
RISK_WEIGHT_FRICTION = 0.10         # §3.9 "0.10 for friction"
FORECAST_BIAS_CAP_PCT = 25          # §3.9 "the forecast_bias_pct capped at 25"
FORECAST_BIAS_NORMALIZER = 4        # §3.9 "and multiplies it by 4"
FRICTION_COUNT_CAP = 5              # §3.9 "the friction_count capped at 5"
FRICTION_UNIT_SCORE = 20            # §3.9 "and multiplies it by 20"
RISK_WATCH_MIN_SCORE = 25           # §3.9 "at least 25 is WATCH"
RISK_AT_RISK_MIN_SCORE = 50         # §3.9 "at least 50 is AT_RISK"
RISK_DELIST_MIN_SCORE = 75          # §3.9 "at least 75 is DELIST_RECOMMENDED"

# --- Pagination (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10       # §2.3 "defaults to 10 when omitted"
PAGINATION_MAX_LIMIT = 100          # §2.3 "bounded above at 100"
