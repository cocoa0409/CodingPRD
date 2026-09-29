"""Domain constants for the hotel night-audit revenue verification API.

Every literal here is taken from the PRD: the API prefix, the role names, the
enum value sets, the calculation constants and the shared "standard property"
configuration used by the composite fixtures.
"""

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

API_PREFIX = "/night-audit"
CLOCK_PATH = "/_clock/set_current_utc"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_PROPERTY_ADMIN = "PropertyAdmin"
ROLE_NIGHT_AUDITOR = "NightAuditor"
ROLE_FRONT_DESK_AGENT = "FrontDeskAgent"
ROLE_OUTLET_MANAGER = "OutletManager"
ROLE_REVENUE_MANAGER = "RevenueManager"
ROLE_CONTROLLER = "Controller"

ALL_ROLES = [
    ROLE_PROPERTY_ADMIN,
    ROLE_NIGHT_AUDITOR,
    ROLE_FRONT_DESK_AGENT,
    ROLE_OUTLET_MANAGER,
    ROLE_REVENUE_MANAGER,
    ROLE_CONTROLLER,
]

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Enum value sets
# ---------------------------------------------------------------------------

OUTLET_STATUSES = ["ACTIVE", "SUSPENDED"]
OUTLET_TYPES = ["FRONT_DESK", "FB_OUTLET", "REMOTE_POS"]

PERIOD_STATUSES = ["OPEN", "TIE_OUT_IN_PROGRESS", "TIE_OUT_FAILED", "TIED_OUT"]

BUSINESS_DATE_STATUSES = [
    "OPEN",
    "ROOM_POSTING",
    "CHARGES_SEALED",
    "SETTLEMENT_REVIEW",
    "BALANCED",
    "CLOSED",
    "REOPENED",
    "ARCHIVED",
]

STAY_STATUSES = ["RESERVED", "IN_HOUSE", "DEPARTED", "NO_SHOW", "CANCELLED"]
SETTLEMENT_STATUSES = [
    "UNSETTLED",
    "PARTIALLY_SETTLED",
    "SETTLED",
    "TRANSFERRED_TO_CITY_LEDGER",
]
MARKET_SEGMENTS = ["TRANSIENT", "GROUP", "CORPORATE", "COMP"]
SETTLEMENT_METHODS = ["CASH", "CREDIT_CARD", "DIRECT_BILL", "HOUSE_ACCOUNT"]

CHARGE_TYPES = [
    "ROOM",
    "OCCUPANCY_TAX",
    "TAX_TRUE_UP",
    "NO_SHOW",
    "LATE_CHECKOUT",
    "MISC_CHARGE",
    "OUTLET_TRANSFER",
    "ALLOWANCE",
    "PAYMENT",
    "DEPOSIT_APPLIED",
    "LEDGER_TRANSFER",
    "CITY_LEDGER_FEE",
]
CLIENT_POSTABLE_CHARGE_TYPES = [
    "MISC_CHARGE",
    "PAYMENT",
    "LEDGER_TRANSFER",
    "DEPOSIT_APPLIED",
]
SOURCE_CHANNELS = [
    "NIGHT_AUDIT",
    "FRONT_DESK",
    "OUTLET_POS",
    "ALLOWANCE_WORKFLOW",
    "LEDGER_SWEEP",
]

TICKET_STATUSES = ["OPEN", "CLOSED", "VOID"]
TICKET_SETTLEMENT_TYPES = ["CASH", "CREDIT_CARD", "ROOM_CHARGE"]

BATCH_STATUSES = [
    "DECLARED",
    "MATCHED",
    "VARIANCE_FLAGGED",
    "RECOUNT_REQUESTED",
    "ACCEPTED_WITH_VARIANCE",
]
TENDER_TYPES = ["CASH", "CREDIT_CARD"]

LEDGER_TYPES = ["HOUSE_ACCOUNT", "CITY_LEDGER", "ADVANCE_DEPOSIT"]

ALLOWANCE_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "RETURNED_FOR_REVISION",
    "APPROVED",
    "POSTED",
    "REJECTED",
    "REVERSED",
]
ALLOWANCE_REASON_CODES = [
    "SERVICE_RECOVERY",
    "RATE_ERROR",
    "POSTING_ERROR",
    "GUEST_DISPUTE",
    "MANAGER_DISCRETION",
]
APPROVAL_ROLES = ["NightAuditor", "RevenueManager", "Controller"]

DOCUMENT_STATUSES = ["PENDING", "ACTIVE", "REJECTED", "REVOKED"]
DOCUMENT_TYPES = ["COMP_ROOM", "RATE_OVERRIDE", "ALLOWANCE_APPROVAL"]
DOCUMENT_DECISIONS = ["APPROVE", "REJECT"]

CARD_AUTH_STATUSES = ["APPROVED", "DECLINED", "EXPIRED", "CAPTURED"]
FOLLOW_UP_STATUSES = ["NOT_REQUIRED", "PENDING", "CONTACTED", "RESOLVED", "ESCALATED"]
FOLLOW_UP_ACTIONS = ["CONTACT", "RESOLVE", "ESCALATE"]
DECLINE_CODES = ["INSUFFICIENT_FUNDS", "EXPIRED_CARD", "DO_NOT_HONOR", "SUSPECTED_FRAUD"]

REPORT_STATUSES = ["DRAFT", "DISTRIBUTED", "SUPERSEDED"]
PACE_BASES = ["CALENDAR_ALIGNED", "WEEKDAY_ALIGNED"]

NO_SHOW_POLICIES = ["FIRST_NIGHT_PLUS_TAX", "FULL_STAY_NO_TAX", "NONE"]

# ---------------------------------------------------------------------------
# Calculation constants (PRD section 2 / section 3)
# ---------------------------------------------------------------------------

TIER_1_MINUTES = 180
TIER_2_MINUTES = 360
TIER_1_PCT = 0.25
TIER_2_PCT = 0.50
TIER_3_PCT = 1.00
LATE_CHECKOUT_FLOOR_AMOUNT = 25.00
SECONDS_PER_DAY = 86400
GL_TIE_OUT_TOLERANCE = 0.00
GL_TIE_OUT_ATTEMPT_LIMIT = 3
AUDIT_RETENTION_YEARS = 7
RECOUNT_LIMIT = 2
REVISION_LIMIT = 2

TAXABLE_CHARGE_TYPES = ["ROOM", "NO_SHOW", "ALLOWANCE"]

# ---------------------------------------------------------------------------
# The shared "standard property" configuration used by the fixtures.
#
# rate_variance_tolerance_pct is deliberately wide (95.0) so that folios booked
# away from the rack rate do not trip the rate-variance gate; the tests that
# exercise that gate narrow it explicitly.
# ---------------------------------------------------------------------------

STANDARD_PROPERTY = {
    "name": "Harbor Grand",
    "room_count_total": 100,
    "standard_room_rate_amount": 200.00,
    "occupancy_tax_rate_pct": 8.875,
    "fb_tax_rate_pct": 6.25,
    "service_charge_pct": 18.0,
    "large_ticket_threshold_amount": 472.00,
    "large_party_discount_pct": 5.0,
    "allowance_manager_threshold_amount": 250.00,
    "allowance_controller_threshold_amount": 1000.00,
    "rate_variance_tolerance_pct": 95.0,
    "settlement_variance_tolerance_amount": 5.00,
    "city_ledger_fee_pct": 1.5,
    "late_checkout_grace_minutes": 30,
    "card_authorization_valid_days": 7,
    "no_show_charge_policy": "FIRST_NIGHT_PLUS_TAX",
}

STANDARD_OUT_OF_ORDER_ROOM_COUNT = 4
STANDARD_ROOMS_AVAILABLE = 96

BUSINESS_DATE_D1 = "2026-08-01"
BUSINESS_DATE_D2 = "2026-08-02"
BUSINESS_DATE_D3 = "2026-08-03"
