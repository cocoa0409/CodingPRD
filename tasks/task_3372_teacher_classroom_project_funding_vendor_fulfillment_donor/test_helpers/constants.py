"""Domain thresholds and shared fixture values for the teacher-classroom-funding API.

Every number here is stated in the PRD: the logical clock's starting instant,
the goal range, the shipping-quote constants, the equity-score weights and
bands, the choice window, the vendor ship SLA, and the match-ratio bound.
"""

# Logical clock (PRD section 2.4): the instant a fresh deployment reports.
BASE_CLOCK = "2026-09-01T00:00:00Z"

# Goal range enforced at project submit (PRD section 3.3).
GOAL_MIN_CENTS = 10000
GOAL_MAX_CENTS = 200000

# Shipping quote constants (PRD section 3.2).
TIER1_MAX_OZ = 32
TIER1_BASE_CENTS = 299
TIER2_MAX_OZ = 128
TIER2_BASE_CENTS = 599
TIER3_BASE_CENTS = 899
ZONE_RATE_CENTS = {"A": 120, "B": 180, "C": 260}
FRAGILE_FLAT_CENTS = 350
SHIPPING_FEE_MIN_CENTS = 199
SHIPPING_FEE_CAP_CENTS = 4999

# Equity score weights and band boundaries (PRD section 3.1).
POVERTY_WEIGHT = 0.7
ELL_WEIGHT = 0.3
BAND_HIGH = 90.0
BAND_MID = 75.0
BAND_LOW = 50.0

# Windows and SLAs (PRD sections 2.4, 3.6, 3.7).
CHOICE_WINDOW_DAYS = 14
VENDOR_SHIP_SLA_DAYS = 10

# Match ratio upper bound (PRD section 3.9).
MATCH_RATIO_MAX = 2.0

# Donation principal floor (PRD section 3.5).
DONATION_MIN_CENTS = 100

# ---------------------------------------------------------------------------
# Shared fixture geometry.
#
# The canonical project used across the suite: 4 units of a 2500-cent, 10-oz,
# zone-A book. Its shipping quote is 40 oz -> tier 2 base 599, pounds
# ceil(40/16) = 3 at 120 cents, no fragile -> 599 + 360 = 959 cents, so the
# goal is 4 * 2500 + 959 = 10959 cents with a 30-day funding window.
# ---------------------------------------------------------------------------
BOOK_ITEM_PRICE_CENTS = 2500
BOOK_ITEM_WEIGHT_OZ = 10
BOOK_SHIPPING_CENTS = 959
BOOK_PROJECT_GOAL_CENTS = 10959
FUNDING_WINDOW_DAYS = 30

# Instants derived from the clock start plus the fixture window lengths.
FUNDING_DEADLINE = "2026-10-01T00:00:00Z"  # BASE_CLOCK + 30 days
CHOICE_DEADLINE = "2026-10-15T00:00:00Z"  # sweep at FUNDING_DEADLINE + 14 days
AFTER_CHOICE_DEADLINE = "2026-10-20T00:00:00Z"

# Standard review-pair identities (opaque reviewer ids).
REVIEWER_SCREENER = "rev-ana"
REVIEWER_VETTER = "rev-ben"
