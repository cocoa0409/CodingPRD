"""Domain thresholds and canonical literals — every value mirrors the PRD.

No constant here is decorative: each one is referenced by factories,
fixtures or Stage-2 tests, and each value is fixed by the PRD contract.
"""

# ---------------------------------------------------------------------------
# Platform / logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
API_PREFIX = "/brand-ops"
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"  # startup default logical time
CLOCK_PATH = "/_clock/set_current_utc"      # mounted OUTSIDE the prefix

# ---------------------------------------------------------------------------
# Brand protection posture (PRD §3.1)
# ---------------------------------------------------------------------------
POSTURE_CRITICAL_SEVERITY_SUM = 10      # CRITICAL when open-case severities sum >= 10
POSTURE_ELEVATED_SEVERITY_SUM = 6       # ELEVATED when sum >= 6
POSTURE_CRITICAL_SINGLE_SEVERITY = 5    # any open severity-5 case => CRITICAL
POSTURE_BREACH_WINDOW_DAYS = 180        # for-cause revocations counted over trailing 180 days
POSTURE_CRITICAL_BREACH_COUNT = 2       # >= 2 recent breaches => CRITICAL

# ---------------------------------------------------------------------------
# Genericization risk (PRD §3.9)
# ---------------------------------------------------------------------------
GENERIC_PUBLISHED_FLAGGED_BPS = 100     # per flagged PUBLISHED submission
GENERIC_VERIFIED_FLAGGED_BPS = 50       # per flagged VERIFIED submission
GENERIC_RISK_CAP_BPS = 10000            # risk capped at 10000
GENERIC_PUBLISH_GATE_BPS = 500          # flagged publish requires risk < 500

# ---------------------------------------------------------------------------
# Line dilution cost (PRD §3.2)
# ---------------------------------------------------------------------------
DILUTION_BASE_COST_BPS = 400            # non-core base cost
DILUTION_PER_EXTRA_CHANNEL_BPS = 150    # per target channel beyond the first
DILUTION_NOVEL_DELIVERY_BPS = 200       # novelty surcharge vs other LAUNCHED lines
DILUTION_COST_CAP_BPS = 1000            # total cost cap

# ---------------------------------------------------------------------------
# Brand equity ledger (PRD §3.1 / §3.2)
# ---------------------------------------------------------------------------
TOTAL_IDENTITY_BPS = 10000              # the whole brand in basis points
DEFAULT_EQUITY_BUDGET_BPS = 10000       # equity_budget_bps default
DISCONTINUED_REFUND_DIVISOR = 2         # discontinued lines refund floor(cost/2)
MIN_CORE_IDENTITY_SHARE_BPS = 7000      # launch requires post-launch share >= 7000
BRAND_REVIEW_MAX_ATTEMPTS = 3           # third REJECT auto-discontinues

# ---------------------------------------------------------------------------
# Coverage attainment (PRD §3.6)
# ---------------------------------------------------------------------------
ATTAINMENT_WINDOW_MONTHS = 3            # trailing 3 completed months
ATTAINMENT_QUOTA_DIVISOR = 4            # 3-month quota = floor(annual_quota_units / 4)
TIER_GOLD_BPS = 12000                   # GOLD at >= 12000
TIER_STANDARD_BPS = 10000               # STANDARD at >= 10000
TIER_WATCH_BPS = 9000                   # WATCH at >= 9000 (else SANCTION)

# ---------------------------------------------------------------------------
# Distributor rebate (PRD §3.6)
# ---------------------------------------------------------------------------
REBATE_GOLD_BPS = 300
REBATE_STANDARD_BPS = 200
REBATE_WATCH_BPS = 100
REBATE_SANCTION_BPS = 0
REBATE_NULL_TIER_BPS = 0
REBATE_MASS_CHANNEL_BONUS_BPS = 25      # MASS in channels_served
REBATE_CAP_BPS = 350                    # min(base + bonus, 350)

# ---------------------------------------------------------------------------
# Registration renewal window (PRD §3.4)
# ---------------------------------------------------------------------------
RENEWAL_WINDOW_DAYS = 90                # window opens at expires_on - 90 days, inclusive

# ---------------------------------------------------------------------------
# Promotion discipline (PRD §3.8)
# ---------------------------------------------------------------------------
PROMO_DEPTH_CAP_NORMAL = 25.00          # discount_pct cap at posture NORMAL
PROMO_DEPTH_CAP_ELEVATED = 15.00        # ... at ELEVATED
PROMO_DEPTH_CAP_CRITICAL = 5.00         # ... at CRITICAL
PROMO_MAX_DISCOUNT_PCT = 90.00          # request-shape ceiling for discount_pct
PROMO_FREQUENCY_MAX_PEERS = 2           # peers within +/-90 days must number < 2
PROMO_FREQUENCY_WINDOW_DAYS = 90
PROMO_MIN_GAP_DAYS = 14                 # every peer starts_on >= 14 days away

# ---------------------------------------------------------------------------
# Coverage cells (PRD §3.5)
# ---------------------------------------------------------------------------
CELL_CAPACITY = 3                       # max ACTIVE+SUSPENDED assignments per cell

# ---------------------------------------------------------------------------
# Distributor strike system (PRD §3.5)
# ---------------------------------------------------------------------------
MAX_SUSPENSIONS = 3                     # a suspension reaching 3 terminates instead

# ---------------------------------------------------------------------------
# Formulations / compartmentalization (PRD §3.3)
# ---------------------------------------------------------------------------
MIN_SEAL_COMPONENTS = 3                 # sealing requires at least 3 components
MAX_COMPONENTS = 12                     # component_codes holds 1..12 entries
COMPARTMENT_SCOPE_NUMERATOR = 1         # |union| * 2 <= |component_codes|
COMPARTMENT_SCOPE_DENOMINATOR = 2
REQUALIFY_BREACH_WINDOW_DAYS = 90       # for-cause revocation blocks requalify 90 days

# ---------------------------------------------------------------------------
# Request-shape ranges (PRD §2.6 rule 4)
# ---------------------------------------------------------------------------
SEVERITY_MIN = 1
SEVERITY_MAX = 5

# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Canonical fixture literals (dates/datetimes used across recipes)
# ---------------------------------------------------------------------------
DEFAULT_COVERAGE_START = "2026-08-01"   # closed window covering the default clock date
DEFAULT_COVERAGE_END = "2027-07-31"
DEFAULT_PRICE_EFFECTIVE_FROM = "2026-08-01T00:00:00Z"
DEFAULT_PRICE_EFFECTIVE_TO = "2027-08-01T00:00:00Z"
GRANT_EXPIRY_FAR_FUTURE = "2027-12-31T00:00:00Z"
REGISTRATION_EXPIRY_DEFAULT = "2027-01-01T00:00:00Z"

# Attainment window months at the startup clock (2026-09): {2026-06, 2026-07, 2026-08}
WINDOW_MONTH_JUN = "2026-06"
WINDOW_MONTH_JUL = "2026-07"
WINDOW_MONTH_AUG = "2026-08"
OUT_OF_WINDOW_MONTH_MAY = "2026-05"
CURRENT_MONTH_AT_DEFAULT = "2026-09"
FUTURE_MONTH_AT_DEFAULT = "2026-10"
