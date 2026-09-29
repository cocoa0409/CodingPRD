"""Domain constants for the Markdown Optimization & Season Exit API test suite.

Every value here is taken verbatim from PRD.md. Nothing is inferred from an
implementation.
"""

# --------------------------------------------------------------------------
# Roles (PRD 2.1 -- "Exactly five roles exist, spelled precisely as follows.")
# --------------------------------------------------------------------------
ROLE_PRICING_ANALYST = "PricingAnalyst"
ROLE_MERCHANDISE_DIRECTOR = "MerchandiseDirector"
ROLE_STORE_MANAGER = "StoreManager"
ROLE_VENDOR_REP = "VendorRep"
ROLE_CONTROLLER = "Controller"

ALL_ROLES = [
    ROLE_PRICING_ANALYST,
    ROLE_MERCHANDISE_DIRECTOR,
    ROLE_STORE_MANAGER,
    ROLE_VENDOR_REP,
    ROLE_CONTROLLER,
]

# --------------------------------------------------------------------------
# The logical clock (PRD 2.5)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Global numeric constants (PRD 2.7, 3.5, 3.6, 3.7)
# --------------------------------------------------------------------------
MIN_CADENCE_DAYS = 14
MAX_LADDER_STEPS = 4
EXIT_BUFFER_DAYS = 7
MAX_REVISION_ROUNDS = 3
MAX_NEGOTIATION_ROUNDS = 4
EXIT_WINDOW_TRIGGER_PCT = 60.0
EXIT_DEPTH_PCT = 50.0

DEPTH_PCT_MIN = 0.01
DEPTH_PCT_MAX = 70.00

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Signage lead defaults by zone type (PRD 3.1)
# --------------------------------------------------------------------------
SIGNAGE_LEAD_DEFAULT_DAYS = {
    "CHAIN": 10,
    "REGION": 7,
    "STORE": 3,
}

# --------------------------------------------------------------------------
# Protected new-arrival periods in days, by category (PRD 3.2)
# --------------------------------------------------------------------------
PROTECTED_NEW_ARRIVAL_DAYS = {
    "APPAREL": 42,
    "FOOTWEAR": 56,
    "ACCESSORIES": 28,
    "SEASONAL_DECOR": 21,
}

# --------------------------------------------------------------------------
# Lifecycle classification constants (PRD 3.3)
# --------------------------------------------------------------------------
AGING_WEEKS = 10
SLOW_SELLER_ST_PCT = 45.0
SLOW_SELLER_MIN_WEEKS = 6
CLEARANCE_WEEKS = 6
EXIT_PENDING_WEEKS = 2

# --------------------------------------------------------------------------
# Elasticity constants (PRD 3.4)
# --------------------------------------------------------------------------
MIN_SAMPLE_WEEKS = 4
HIGH_CONFIDENCE_WEEKS = 4
ELASTICITY_FLOOR = -4.0
ELASTICITY_CAP = -0.2

# --------------------------------------------------------------------------
# Recommended-depth constants (PRD 3.5)
# --------------------------------------------------------------------------
BASE_DEPTH_PCT = {
    "NEW_ARRIVAL": 0.0,
    "CORE": 5.0,
    "AGING": 15.0,
    "CLEARANCE": 30.0,
    "EXIT_PENDING": 50.0,
    "DISPOSED": 0.0,
}
TARGET_WEEKS_OF_SUPPLY = 4.0
PRESSURE_PER_WEEK_PCT = 1.5
PRESSURE_CAP_PCT = 15.0
ELASTICITY_PIVOT = 1.5
ELASTICITY_FACTOR_FLOOR = 0.6
ELASTICITY_FACTOR_CAP = 1.4
MIN_DEPTH_PCT = 10.0
MAX_DEPTH_PCT = 70.0

# --------------------------------------------------------------------------
# Disposition recovery constants (PRD 3.9)
# --------------------------------------------------------------------------
JOBBER_FREIGHT_PCT = 8.0
DONATION_CREDIT_PCT = 21.0

# --------------------------------------------------------------------------
# Sentinel weeks-of-supply when there is no history to divide by (PRD 3.2)
# --------------------------------------------------------------------------
WEEKS_OF_SUPPLY_SENTINEL = 999.99

# --------------------------------------------------------------------------
# Enumerations (PRD 3.1 - 3.9)
# --------------------------------------------------------------------------
CATEGORIES = ["APPAREL", "FOOTWEAR", "ACCESSORIES", "SEASONAL_DECOR"]

SEASON_STATUSES = ["PLANNING", "ACTIVE", "EXIT_WINDOW", "CLOSED"]

ZONE_TYPES = ["CHAIN", "REGION", "STORE"]

STORE_STATUSES = ["OPEN", "REMODEL", "CLOSING"]

LIFECYCLE_STAGES = [
    "NEW_ARRIVAL",
    "CORE",
    "AGING",
    "CLEARANCE",
    "EXIT_PENDING",
    "DISPOSED",
]

MARKDOWN_STATES = [
    "FULL_PRICE",
    "PROMO_ACTIVE",
    "PERM_MARKED",
    "EXIT_PRICED",
    "SETTLED",
]

ESTIMATE_METHODS = ["AUTO", "OWN_HISTORY", "CLUSTER_POOLED"]
RESOLVED_METHODS = ["OWN_HISTORY", "CLUSTER_POOLED"]
ESTIMATE_STATUSES = ["DRAFT", "CERTIFIED", "SUPERSEDED"]
CONFIDENCE_LEVELS = ["HIGH", "LOW"]

PLAN_TYPES = ["PERMANENT", "PROMOTIONAL"]
PLAN_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "APPROVED",
    "EXECUTING",
    "COMPLETED",
    "SUPERSEDED",
]

STEP_STATUSES = ["PLANNED", "SCHEDULED", "EXECUTED", "SUPERSEDED"]

EXECUTION_SCOPES = ["CHAIN", "ZONE", "STORE"]
EXECUTION_STATUSES = ["SCHEDULED", "APPLIED", "ROLLED_BACK"]
SIGNAGE_STATUSES = ["PENDING", "POSTED", "NON_COMPLIANT", "VERIFIED"]

RESERVATION_STATUSES = ["RESERVED", "COMMITTED", "RELEASED"]

AGREEMENT_STATUSES = ["PROPOSED", "COUNTERED", "AGREED", "FUNDED", "EXPIRED"]

CLAIM_STATUSES = ["SUBMITTED", "RECOGNIZED", "REJECTED", "REVERSED"]
CLAIM_REJECTION_REASONS = ["CAP_EXHAUSTED", "AGREEMENT_EXPIRED"]

DISPOSITION_CHANNELS = ["SALVAGE", "JOBBER", "DONATION"]
DISPOSITION_STATUSES = ["DRAFT", "APPROVED", "SETTLED", "CANCELLED"]

REVIEW_TYPES = ["PRELIMINARY", "FINAL"]
