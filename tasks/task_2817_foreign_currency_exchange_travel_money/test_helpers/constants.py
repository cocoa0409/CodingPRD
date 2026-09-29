"""Domain thresholds and pinned numeric constants of the Retail FX & Travel Money API.

Every value here is quoted from the PRD narrative; nothing is invented. All money is
whole US cents, all foreign cash is whole minor units, all rates are micros and all
ratios are basis points (PRD 2.5).
"""

# --- PRD 2.3 pagination -------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
    "MIN_OFFSET": 0,
}

# --- PRD 2.4 logical clock ----------------------------------------------------
# "At start-up the logical clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_START = "2026-08-01T00:00:00Z"

# --- PRD 2.5 scales -----------------------------------------------------------
MICROS = 1_000_000
BPS_ONE = 10_000

# --- PRD 2.6 vault posture bands ---------------------------------------------
VAULT_RESTRICTED_MIN_BPS = 9000
VAULT_FROZEN_MIN_BPS = 10000
MIN_VAULT_LIMIT_USD_CENTS = 100_000

# --- PRD 3.9 automatic repatriation ------------------------------------------
VAULT_TARGET_BPS = 8500

# --- PRD 3.3 seasonal planning ----------------------------------------------
EXOTIC_PLAN_CAP_MINOR_UNITS = 5_000_000
RESTRICTED_EXPORT_MULTIPLE = 2
PLAN_VAULT_SHARE_BPS = 2500

# --- PRD 3.5 commission schedule --------------------------------------------
COMMISSION_TIER_1_CEILING_CENTS = 25_000
COMMISSION_TIER_2_CEILING_CENTS = 100_000
COMMISSION_TIER_1_BPS = 350
COMMISSION_TIER_2_BPS = 250
COMMISSION_TIER_3_BPS = 150
COMMISSION_PREMIUM_UPLIFT_BPS = 50
COMMISSION_MIN_CENTS = 400

# --- PRD 3.5 quote / reversal windows ---------------------------------------
QUOTE_TTL_MINUTES = 15
REVERSAL_WINDOW_HOURS = 24

# --- PRD 2.8 rank 8 / rank 9 thresholds -------------------------------------
ID_REQUIRED_CENTS = 100_000
DUAL_CONTROL_THRESHOLD_CENTS = 500_000

# --- PRD 3.6 structuring surveillance ---------------------------------------
NEAR_THRESHOLD_FLOOR_CENTS = 800_000
REPORT_THRESHOLD_CENTS = 1_000_000
ROLLING_WINDOW_DAYS = 30
VOLUME_COMPONENT_MAX = 40
FREQUENCY_COMPONENT_MAX = 35
DISPERSION_COMPONENT_MAX = 25
NEAR_THRESHOLD_POINTS = 11
DISPERSION_POINTS = 12
RISK_TIER_ELEVATED_MIN = 25
RISK_TIER_HIGH_MIN = 70

# --- PRD 3.7 buy-back guarantees --------------------------------------------
BUYBACK_FEE_BPS = 300
BUYBACK_FEE_MIN_CENTS = 200
RATE_LOCK_DAYS = 31

# --- PRD 2.10 disclosure regime ---------------------------------------------
MIN_DISCLOSURE_TEXT_VERSION = 3
DEFAULT_DAMAGED_NOTE_RECOVERY_BPS = 6500

# --- PRD 3.9 armored transport ----------------------------------------------
MIN_ROUTE_GAP_MINUTES = 45

# --- Enum domains (PRD 2.10, 3.1-3.9) ---------------------------------------
ROLES = [
    "PlatformAdmin",
    "TreasuryOfficer",
    "BranchManager",
    "BranchTeller",
    "ComplianceOfficer",
    "Customer",
]
BRANCH_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
BRANCH_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
CURRENCY_CLASSES = ["MAJOR", "EXOTIC", "RESTRICTED"]
MINOR_UNIT_DIGITS = [0, 2, 3]
WHOLESALE_SOURCE_CODES = ["REUTERS_MID", "INTERBANK_CLOSE"]
RATE_CARD_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED"]
COMMISSION_SCHEDULE_CODES = ["STANDARD", "PREMIUM"]
POSITION_STATUSES = ["OPEN", "CLOSED"]
SEASONS = ["SPRING", "SUMMER", "AUTUMN", "WINTER"]
PLAN_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "ACTIVE"]
PLAN_DECISIONS = ["APPROVE", "REJECT"]
ID_DOCUMENT_TYPES = ["PASSPORT", "NATIONAL_ID", "DRIVING_LICENCE"]
RISK_TIERS = ["NORMAL", "ELEVATED", "HIGH"]
DIRECTIONS = ["SELL_FX_TO_CUSTOMER", "BUY_FX_FROM_CUSTOMER"]
SETTLEMENT_STATUSES = ["QUOTED", "AUTHORIZED", "SETTLED", "VOIDED", "REVERSED"]
COMPLIANCE_STATUSES = ["PENDING", "FLAGGED", "CLEARED", "BLOCKED"]
COMPLIANCE_DECISIONS = ["CLEAR", "FLAG", "BLOCK"]
HOLD_ACTIONS = ["APPLY", "RELEASE"]
CONTRACT_STATUSES = [
    "ISSUED",
    "PARTIALLY_REDEEMED",
    "REDEEMED",
    "CANCELLED",
    "EXPIRED",
]
DEFECT_TYPES = ["SUSPECTED_COUNTERFEIT", "DAMAGED", "OBSOLETE_SERIES"]
ASSESSMENT_OUTCOMES = ["CONFISCATED", "RETURNED", "EXCHANGED_AT_DISCOUNT"]
ASSESSMENT_STATUSES = ["SUBMITTED", "ASSESSED"]
REPORT_TYPES = ["THRESHOLD_REPORT", "STRUCTURING_SUSPICION", "COUNTERFEIT_SEIZURE"]
REPORT_STATUSES = ["DRAFT", "FILED", "AMENDING"]
SHIPMENT_DIRECTIONS = ["REPLENISHMENT", "REPATRIATION"]
SHIPMENT_STATUSES = [
    "REQUESTED",
    "SCHEDULED",
    "IN_TRANSIT",
    "DELIVERED",
    "EXCEPTION",
    "RECONCILED",
]
EXCEPTION_REASONS = ["MANIFEST_VARIANCE"]

# --- Test-world defaults ------------------------------------------------------
# The recurring reference world: one southern branch, the euro, one wholesale mid
# and a 550/450 board line.  Derived board rates (PRD 3.2):
#   sell_rate_micros = round_half_up(920000 * (10000 - 450) / 10000) = 878600
#   buy_rate_micros  = round_half_up(920000 * (10000 + 550) / 10000) = 970600
TEST_DEFAULTS = {
    "BRANCH_CODE": "BR-LHR",
    "BRANCH_NAME": "London Heathrow",
    "REGION_CODE": "SOUTH",
    "VAULT_LIMIT_USD_CENTS": 20_000_000,
    "EUR_MID_RATE_MICROS": 920_000,
    "EUR_DENOMINATIONS": [500, 1000, 2000, 5000, 10000],
    "EUR_SELL_RATE_MICROS": 878_600,
    "EUR_BUY_RATE_MICROS": 970_600,
    "CHF_MID_RATE_MICROS": 912_345,
    "CHF_DENOMINATIONS": [1000, 2000, 5000, 20000],
    "BUY_SPREAD_BPS": 550,
    "SELL_SPREAD_BPS": 450,
    "WHOLESALE_EFFECTIVE_AT": "2026-07-01T00:00:00Z",
    "SOURCE_CODE": "REUTERS_MID",
    "CUSTOMER_NAME": "Nia Adeyemi",
    "NATIONALITY_CODE": "GH",
}

# Recurring opaque operator identifiers.  PRD 2.1: for the five staff roles the
# X-User-ID is an opaque operator identifier that is never compared to a row id.
OPERATORS = {
    "ADMIN": "admin-01",
    "TELLER_1": "teller-01",
    "TELLER_2": "teller-02",
    "MANAGER": "mgr-01",
    "TREASURY": "treas-01",
    "TREASURY_ALT": "trs-09",
    "COMPLIANCE": "comp-01",
}
