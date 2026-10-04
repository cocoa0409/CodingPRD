"""All named constants for the Fast-Follow Beauty platform.

Every constant referenced anywhere in the implementation is defined exactly
once, here. Values come from SCAFFOLD.yaml calculations tables and PRD text.
"""
from decimal import Decimal

# --- Logical clock (PRD 2.4) -------------------------------------------------
# Before any clock-set call, the logical clock reads exactly this instant.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Roles (PRD 2.1) ----------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_TREND_SCOUT = "TrendScout"
ROLE_PRODUCT_MANAGER = "ProductManager"
ROLE_SOURCING_LEAD = "SourcingLead"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_RETAIL_PLANNER = "RetailPlanner"
ROLE_MARKETING_LEAD = "MarketingLead"
ROLE_MANUFACTURER_REP = "ManufacturerRep"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_TREND_SCOUT,
    ROLE_PRODUCT_MANAGER,
    ROLE_SOURCING_LEAD,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RETAIL_PLANNER,
    ROLE_MARKETING_LEAD,
    ROLE_MANUFACTURER_REP,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# --- Pagination (scaffold response_envelope.pagination_defaults) --------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# --- Trend momentum score (calculations.trend_momentum_score) -----------------
VELOCITY_CAP_PER_DAY = 5000
GROWTH_CAP = Decimal("2.0")
W_VELOCITY = Decimal("0.5")
W_GROWTH = Decimal("0.3")
W_SIGNAL = Decimal("0.2")
TREND_SELECT_THRESHOLD = Decimal("70.0")

# --- Fixed price points & cost-target tiers (calculations.target_unit_cost) ---
PRICE_POINTS = (300, 600, 1000, 1500, 2000)
# ratio steps down as the price point rises (PRD 3.2)
COST_RATIO_T1_MAX = 600    # <= 600 -> 28%
COST_RATIO_T2_MAX = 1000   # <= 1000 -> 26%
COST_RATIO_T3_MAX = 1500   # <= 1500 -> 24%
#                        <= 2000 -> 22%
COST_RATIO_T1 = Decimal("0.28")
COST_RATIO_T2 = Decimal("0.26")
COST_RATIO_T3 = Decimal("0.24")
COST_RATIO_T4 = Decimal("0.22")

# --- Formula projects (PRD 3.4) ------------------------------------------------
COMPRESSED_FORMULA_WEEKS = 6
MAX_FORMULA_ROUNDS = 3

# --- Packaging lead time (calculations.packaging_lead_time) -------------------
TOOLING_NEW_WEEKS = 14
TOOLING_REUSE_WEEKS = 5

# --- Cruelty-free certification validity (PRD 3.6) ----------------------------
CERT_VALIDITY_DAYS = 365

# --- Launch quantity (calculations.launch_quantity) ---------------------------
FACINGS_WEEKLY_SELLTROUGH = 12
LAUNCH_WEEKS = 8
TREND_DECAY_PCT_PER_WEEK = Decimal("0.05")
MARKDOWN_RISK_CAP = Decimal("0.40")

# --- Markdown depth tiers (calculations.markdown_exposure) --------------------
MARKDOWN_TIER1_MAX_WEEKS = 4
MARKDOWN_TIER2_MAX_WEEKS = 8
MARKDOWN_TIER3_MAX_WEEKS = 12
MARKDOWN_DEPTH_T1 = Decimal("0.00")
MARKDOWN_DEPTH_T2 = Decimal("0.30")
MARKDOWN_DEPTH_T3 = Decimal("0.50")
MARKDOWN_DEPTH_T4 = Decimal("0.70")

# --- Sampling (calculations.sampling_burn) ------------------------------------
SAMPLE_CAP_PCT = Decimal("0.10")

# --- Occupancy reset buffer (validations priority 22) -------------------------
RESET_GAP_DAYS = 14

# --- Trend signal sources ------------------------------------------------------
SOURCE_SOCIAL_PLATFORM = "SOCIAL_PLATFORM"
SOURCE_PRESTIGE_LAUNCH = "PRESTIGE_LAUNCH"
