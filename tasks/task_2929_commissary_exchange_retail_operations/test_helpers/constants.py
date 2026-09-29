"""Domain constants for the Commissary & Exchange Retail Operations API.

Every value here is stated in PRD.md; nothing is invented. Money is always an
integer number of cents and every rate is an integer number of basis points.
"""

# ---------------------------------------------------------------------------
# The logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

# "The logical clock's startup value is exactly 2026-08-01T00:00:00Z."
CLOCK_START = "2026-08-01T00:00:00Z"


def midnight_utc(year: int, month: int, day: int) -> str:
    """An ISO 8601 UTC instant at midnight, the form the API accepts."""
    return f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"


# Named instants used by the fixtures. All are ISO 8601 UTC instants, never
# date-only strings.
JUN_01 = midnight_utc(2026, 6, 1)
JUN_15 = midnight_utc(2026, 6, 15)
AUG_01 = midnight_utc(2026, 8, 1)
AUG_02 = midnight_utc(2026, 8, 2)
AUG_03 = midnight_utc(2026, 8, 3)
AUG_04 = midnight_utc(2026, 8, 4)
AUG_05 = midnight_utc(2026, 8, 5)
AUG_06 = midnight_utc(2026, 8, 6)
AUG_07 = midnight_utc(2026, 8, 7)
AUG_08 = midnight_utc(2026, 8, 8)
AUG_09 = midnight_utc(2026, 8, 9)
AUG_10 = midnight_utc(2026, 8, 10)
AUG_11 = midnight_utc(2026, 8, 11)
AUG_12 = midnight_utc(2026, 8, 12)
AUG_13 = midnight_utc(2026, 8, 13)
AUG_15 = midnight_utc(2026, 8, 15)
AUG_20 = midnight_utc(2026, 8, 20)
AUG_25 = midnight_utc(2026, 8, 25)
AUG_31 = midnight_utc(2026, 8, 31)
SEP_01 = midnight_utc(2026, 9, 1)
DEC_31 = midnight_utc(2026, 12, 31)

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Store registration dials (PRD 3.1)
# ---------------------------------------------------------------------------

DEFAULT_SURCHARGE_RATE_BP = 500
MAX_SURCHARGE_RATE_BP = 1000
DEFAULT_EXCHANGE_MARKUP_BP = 0
MAX_EXCHANGE_MARKUP_BP = 5000
DEFAULT_SHELF_BLOCK_CAPACITY_FACINGS = 24

# ---------------------------------------------------------------------------
# Store fund posture thresholds (PRD 2.9)
# ---------------------------------------------------------------------------

POSTURE_UNRESTRICTED_MIN_CENTS = 500000
POSTURE_CONSTRAINED_MIN_CENTS = 100000

# ---------------------------------------------------------------------------
# Product defaults (PRD 3.4)
# ---------------------------------------------------------------------------

DEFAULT_UNIT_WEIGHT_GRAMS = 500
DEFAULT_PROMO_ALLOWANCE_BP = 0
MAX_PROMO_ALLOWANCE_BP = 2000
DEFAULT_OVERSEAS_SHIPPING_ALLOWANCE_CENTS = 0

# ---------------------------------------------------------------------------
# Special order freight (PRD 3.8)
# ---------------------------------------------------------------------------

FREIGHT_RATE_CENTS_PER_KG = {
    "CONUS": 0,
    "OVERSEAS": 210,
    "DEPLOYED": 340,
}
PATRON_SHIPPING_SHARE_BP = 2500
SHIPPING_ALLOWANCE_CAP_CENTS = 15000

# ---------------------------------------------------------------------------
# Resale compliance scoring (PRD 3.7)
# ---------------------------------------------------------------------------

RESTRICTED_UNIT_POINTS = 12
STRIKE_POINTS = 25
RISK_SCORE_CAP = 100
WATCH_RESTRICTED_MIN_SCORE = 85
WATCH_MIN_SCORE = 60
CARD_SUSPENSION_MIN_SCORE = 80
ROLLING_WINDOW_DAYS = 30
RECENT_SALES_WINDOW_SIZE = 5

# ---------------------------------------------------------------------------
# Capital project contingency tiers (PRD 3.9)
# ---------------------------------------------------------------------------

CONTINGENCY_TIER_SMALL_MAX_EXCLUSIVE_CENTS = 500000
CONTINGENCY_TIER_MEDIUM_MAX_EXCLUSIVE_CENTS = 2000000
CONTINGENCY_BP_SMALL = 1000
CONTINGENCY_BP_MEDIUM = 700
CONTINGENCY_BP_LARGE = 500

# ---------------------------------------------------------------------------
# Enumerations (PRD 3.x)
# ---------------------------------------------------------------------------

CHANNELS = ("COMMISSARY", "EXCHANGE")
REGIONS = ("CONUS", "OVERSEAS", "DEPLOYED")

ID_CARD_CLASSES = (
    "ACTIVE_DUTY",
    "RETIREE",
    "DEPENDENT",
    "DISABLED_VETERAN",
    "GUARD_RESERVE",
    "DOD_CIVILIAN_OVERSEAS",
)

PRODUCT_CATEGORIES = (
    "GROCERY_STAPLE",
    "INFANT_FORMULA",
    "TOBACCO",
    "ALCOHOL",
    "GENERAL_MERCHANDISE",
)

SUPPLY_MODES = ("WAREHOUSE", "DSD")

CARD_STATUSES = ("VALID", "SUSPENDED", "REVOKED")
SUSPENSION_REASONS = ("ADMIN_ACTION", "SPONSOR_SUSPENDED", "RISK_THRESHOLD")
RESALE_WATCH_STATUSES = ("CLEAR", "WATCH", "RESTRICTED")

DELEGATION_STATUSES = (
    "ACTIVE",
    "REVOKED",
    "EXPIRED",
    "SUPERSEDED",
    "SUSPENDED_BY_SPONSOR",
)

ASSORTMENT_STATUSES = ("ACTIVE", "RETIRED")

TENDER_STATES = ("OPEN", "TENDERED", "VOIDED")
COMPLIANCE_STATES = ("CLEARED", "FLAGGED")
VOIDED_REASONS = ("RESALE_VIOLATION", "OPERATOR_ERROR", "COMPLIANCE_HOLD")

FUNDS = ("SURCHARGE", "DIVIDEND")
LEDGER_ENTRY_TYPES = (
    "SURCHARGE_COLLECTION",
    "SURCHARGE_REVERSAL",
    "CAPITAL_OUTLAY",
    "ALLOWANCE_CREDIT",
    "ALLOWANCE_REVERSAL",
    "DIVIDEND_TRANSFER",
)
SOURCE_REF_KINDS = ("SALE", "CAPITAL_PROJECT", "MWR_PROGRAM", "SPECIAL_ORDER")

PROJECT_STATES = (
    "DRAFT",
    "SUBMITTED",
    "RETURNED_FOR_REVISION",
    "AWAITING_FUNDS",
    "APPROVED",
    "REJECTED",
    "CLOSED",
)
PROJECT_DECISIONS = ("APPROVE", "RETURN", "REJECT")

MWR_PROGRAM_STATUSES = ("ACTIVE", "SUSPENDED")

SPECIAL_ORDER_STATES = (
    "SUBMITTED",
    "LOCAL_FILL_PENDING",
    "OVERSEAS_SHIP_PENDING",
    "FULFILLED",
    "CANCELLED",
)
SPECIAL_ORDER_ROUTES = ("LOCAL_FILL", "OVERSEAS_SHIP")
CANCELLED_REASONS = ("PATRON_REQUEST", "ASSORTMENT_RETIRED")

CARD_ACTIONS = ("SUSPEND", "REINSTATE", "REVOKE")
COMPLIANCE_DECISIONS = ("CONFIRM_STRIKE", "CLEAR_WATCH")

ROLES = (
    "SystemOperator",
    "SurchargeFundController",
    "MwrBoardOfficer",
    "ComplianceOfficer",
    "AssortmentPlanner",
    "StoreCashier",
    "Patron",
)
