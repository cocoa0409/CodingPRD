"""PRD-pinned constants — every numeric threshold, cap, ratio, window length
and tolerance, verbatim from PRD.md / SCAFFOLD.yaml (34 constants)."""

DEFAULT_CLOCK_START_ISO = "2026-09-01T00:00:00Z"  # logical clock default
MAX_NEGOTIATION_ROUNDS = 6        # negotiate rejected (plan auto-EXPIRED) at this round
GROWTH_TARGET_MIN_PCT = -20       # growth_target_pct lower bound (inclusive)
GROWTH_TARGET_MAX_PCT = 50        # growth_target_pct upper bound (inclusive)
FISCAL_YEAR_MIN = 2026
FISCAL_YEAR_MAX = 2030
FUND_ACCRUAL_RATE_MAX_PCT = 5     # accrual_rate_pct in (0, 5]
EVENT_SPLIT_MIN_PCT = 20          # event bucket share >= 20% at activation (edlp cap 80)
CASH_COLLECTION_FACTOR = 0.92     # cash-basis haircut
PROMO_DISCOUNT_DEPTH_MAX_PCT = 40  # discount_depth_pct in (0, 40]
SHELF_SPACE_CHANGE_MAX_PCT = 30   # |space_change_pct| <= 30
SHELF_TARGET_STORE_COUNT_MAX = 10000  # target_store_count in [1, 10000]
IMPLEMENTATION_SLA_DAYS = 90      # shelf-rec verify deadline from accepted_at
CHANNEL_PRICE_GAP_MAX_PCT = 15    # pairwise ppu gap <= 15 (exactly 15 passes)
ECOMMERCE_UNDERCUT_MAX_PCT = 10   # ECOMMERCE ppu >= ceil(min_other * 0.9)
CLUB_PACK_MIN_UNITS = 12          # CLUB packs need unit_count >= 12
LAUNCH_MIN_GAP_DAYS = 84          # min separation of launch_date (>= 84 passes)
REVIEW_MIN_DAYS_AFTER_LAUNCH = 84  # review create at clock >= launch_date + 84d
PHASE_COUNT = 4                   # launch auto-creates exactly 4 phases
DISTRIBUTION_SUM_MAX_PCT = 100    # sum of phase distribution_target_pct <= 100
RISK_WEIGHT_SALES = 0.40
RISK_WEIGHT_DISTRIBUTION = 0.30
RISK_WEIGHT_FORECAST = 0.20
RISK_WEIGHT_FRICTION = 0.10
FORECAST_BIAS_CAP_PCT = 25        # bias input to risk is min(bias_pct, 25)
FORECAST_BIAS_NORMALIZER = 4      # bias component = min(bias,25) * 4
FRICTION_COUNT_CAP = 5            # friction input is min(friction_count, 5)
FRICTION_UNIT_SCORE = 20          # friction component = min(count,5) * 20
RISK_WATCH_MIN_SCORE = 25         # score >= 25 -> WATCH
RISK_AT_RISK_MIN_SCORE = 50       # score >= 50 -> AT_RISK
RISK_DELIST_MIN_SCORE = 75        # score >= 75 -> DELIST_RECOMMENDED
PHASE_WEIGHT_GATE_PASSED = 1.0
PHASE_WEIGHT_PENDING = 0.25
PHASE_WEIGHT_GATE_FAILED = 0.0
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Enum alphabets (PRD-declared memberships).
CHANNELS = ["MASS", "GROCERY", "CLUB", "ECOMMERCE", "CONVENIENCE"]
EVENT_TYPES = ["FEATURE", "DISPLAY", "PRICE_REDUCTION", "IN_STORE_DEMO"]
RETAILER_STATUSES = ["ACTIVE", "SUSPENDED"]
ADVISORY_SCOPES = ["FULL_CATEGORY", "MANUFACTURER_ONLY"]
PLAN_DECISIONS = ["ACCEPT", "REJECT"]
ANALYSIS_DECISIONS = ["ACCEPT", "RETURN"]
SHELF_DECISIONS = ["ACCEPT", "REJECT"]
PPD_DECISIONS = ["APPROVE", "REJECT"]
REVIEW_DECISIONS = ["CONTINUE", "DELIST"]
DEDUCTION_ACTIONS = ["DISPUTE", "SETTLE", "REJECT", "WRITE_OFF"]
DEDUCTION_BUCKETS = ["EDLP", "EVENT"]
PHASE_TYPES_BY_INDEX = {1: "CAPACITY_BUILD", 2: "DISTRIBUTION_BUILD", 3: "TRADE_SPEND", 4: "SUSTAIN"}

# Terminal states per entity (PRD §2.10): absorbing, reject every further
# transition with ERR_ALREADY_TERMINAL.
PLAN_TERMINAL = ("REJECTED", "EXPIRED")
EVENT_TERMINAL = ("CANCELLED",)
ANALYSIS_TERMINAL = ("ACCEPTED", "RETURNED")
SHELF_TERMINAL = ("REJECTED", "VERIFIED", "STALLED", "WITHDRAWN")
LAUNCH_TERMINAL = ("REVIEWED", "DELISTED")
DEDUCTION_TERMINAL = ("SETTLED", "REJECTED", "WRITTEN_OFF")
PPD_TERMINAL = ("REJECTED", "RETIRED")
REVIEW_TERMINAL = ("FINALIZED",)
