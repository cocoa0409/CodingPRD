"""Domain thresholds and constants — every literal is pinned by PRD prose.

Grep evidence (PRD.md):
  BOOT_CLOCK_UTC              §2.4 "the logical clock reads exactly 2026-09-01T00:00:00Z"
  MINT_API_PREFIX             §1   "All business resources are mounted under the `/mint` prefix"
  CLOCK_PATH                  §2.4 "POST /_clock/set_current_utc, which is intentionally mounted
                                    outside the `/mint` prefix"
  PAGINATION_*                §2.3 "limit defaults to 10, with a minimum of 1 and a maximum of 100"
  SUBSCRIBER_DISCOUNT_PCT     §3.7 "discounted by the ten-percent subscriber discount"
  SHIPPING_TIER1_*            §3.7 "495 cents when the cycle ships at most 3 units"
  SHIPPING_TIER2_*            §3.7 "895 cents when it ships 4 to 10 units"
  FREE_SHIPPING_MIN_UNITS     §3.7 "free shipping at 11 units or more"
  ADMIN_FEE_PCT               §3.5 "the administrative fee is that base multiplied by five percent"
  TIER_BPS_*                  §3.8 "300 basis points for T1, 450 for T2, and 625 for T3"
  BRACKET_*                   §3.8 "200 basis points when the total weight is under 100 troy
                                    ounces, 100 basis points from 100 up to but not including
                                    500 troy ounces, and zero at 500 troy ounces or more"
  PREMIUM_BPS_DENOMINATOR     §3.8 "the premium basis points divided by ten thousand"
  VAULT_DAILY_CAPACITY_TONNES §3.2 "must not exceed 50 tonnes"
  ERROR_RATE_THRESHOLD        §3.3 "the ratio of error pieces to struck pieces is at least 0.02"
  ERROR_RATE_WINDOW_DAYS      §3.3 "30 days before the current logical-clock instant"
  RELEASE_MIN_GAP_HOURS       §3.6 "Releases within a family must stand at least 24 hours apart"
  MAX_BILLING_ATTEMPTS        §3.7 "a FAILED invoice already at 3 attempts" is not payable;
                                    the third failed attempt writes the invoice off
  MONTHLY_ADVANCE_MONTHS      §3.7 "advances next_billing_date by one month for MONTHLY"
  QUARTERLY_ADVANCE_MONTHS    §3.7 "or three months for QUARTERLY"
"""

# --- Platform-level clock (PRD §2.4) -----------------------------------------
BOOT_CLOCK_UTC = "2026-09-01T00:00:00Z"  # boot reading; no spot prices at boot
MINT_API_PREFIX = "/mint"
CLOCK_PATH = "/_clock/set_current_utc"  # mounted OUTSIDE the /mint prefix

# --- Pagination (PRD §2.3) ----------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Subscription invoice pricing (PRD §3.7) ----------------------------------
SUBSCRIBER_DISCOUNT_PCT = 0.10           # 10% off, applied per unit before multiply
SHIPPING_TIER1_MAX_UNITS = 3             # units_per_cycle <= 3
SHIPPING_TIER1_CENTS = 495
SHIPPING_TIER2_MAX_UNITS = 10            # 4 <= units_per_cycle <= 10
SHIPPING_TIER2_CENTS = 895
FREE_SHIPPING_MIN_UNITS = 11             # units_per_cycle >= 11 -> 0 cents
MAX_BILLING_ATTEMPTS = 3                 # 3rd failed attempt -> WRITTEN_OFF
MONTHLY_ADVANCE_MONTHS = 1
QUARTERLY_ADVANCE_MONTHS = 3

# --- Commemorative program finances (PRD §3.5) --------------------------------
ADMIN_FEE_PCT = 0.05                     # fee on (gross - direct_costs), round-half-up

# --- Bullion premium schedule (PRD §3.8) --------------------------------------
TIER_BPS = {"T1": 300, "T2": 450, "T3": 625}
BRACKET_BOUNDARY_LOW_OZ = 100            # < 100 oz -> +200 bps
BRACKET_BOUNDARY_HIGH_OZ = 500           # >= 500 oz -> +0 bps
BRACKET_BPS_UNDER_100OZ = 200
BRACKET_BPS_100_TO_499OZ = 100
BRACKET_BPS_500OZ_PLUS = 0
PREMIUM_BPS_DENOMINATOR = 10000

# --- Vault receiving (PRD §3.2) -----------------------------------------------
VAULT_DAILY_CAPACITY_TONNES = 50         # per vault per UTC date, logical clock

# --- Quality gate (PRD §3.3) ---------------------------------------------------
ERROR_RATE_THRESHOLD = 0.02              # >= breaches (exactly 0.02 breaches)
ERROR_RATE_WINDOW_DAYS = 30              # trailing window over the logical clock

# --- Release calendar (PRD §3.6) ----------------------------------------------
RELEASE_MIN_GAP_HOURS = 24               # >= 24h passes, < 24h fails

# --- Test data defaults ---------------------------------------------------------
# Canonical denomination used across circulating-side setups: the QUARTER with
# face 25c, budget blank 4.0c, striking 2.0c -> budgeted unit seigniorage 19.0c.
DEFAULT_DENOMINATION = {
    "code": "QUARTER",
    "face_value_cents": 25,
    "blank_budget_cost_cents": 4.0,
    "striking_cost_cents": 2.0,
    "blanks_per_tonne": 176000,
}
DEFAULT_BUDGETED_UNIT_SEIGNIORAGE_CENTS = 19.0  # 25 - 4.0 - 2.0
DEFAULT_COPPER_SPOT_CENTS_PER_TONNE = 800000
DEFAULT_LOCKED_COPPER_PRICE_CENTS_PER_TONNE = 900000
DEFAULT_LOT_BUDGET_PRICE_CENTS_PER_TONNE = 700000
DEFAULT_GOLD_SPOT_CENTS_PER_OZ = 250000
DEFAULT_PRODUCT_PRICE_CENTS = 2000
DEFAULT_SUBSCRIPTION_PRODUCT_PRICE_CENTS = 9995
