"""
Business constants for the Renewable Land Origination API test suite.

Every value here is taken verbatim from the PRD: role spellings, enum members,
the pinned formula constants, the logical-clock start instant and the
threshold ladders. Nothing here is invented.
"""

# ─── Mount points ─────────────────────────────────────

API_ROOT = "/land-origination"
CLOCK_PATH = "/_clock/set_current_utc"

# ─── Roles (spelled exactly as the PRD spells them) ───

ROLE_LAND_AGENT = "LandAgent"
ROLE_TITLE_COUNSEL = "TitleCounsel"
ROLE_PORTFOLIO_MANAGER = "PortfolioManager"
ROLE_PAYMENT_ADMINISTRATOR = "PaymentAdministrator"
ROLE_LANDOWNER = "Landowner"

ALL_ROLES = [
    ROLE_LAND_AGENT,
    ROLE_TITLE_COUNSEL,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_PAYMENT_ADMINISTRATOR,
    ROLE_LANDOWNER,
]

OPERATOR_ROLES = [
    ROLE_LAND_AGENT,
    ROLE_TITLE_COUNSEL,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_PAYMENT_ADMINISTRATOR,
]

# A syntactically well-formed but undeclared role spelling.
UNDECLARED_ROLE = "TitleAuditor"

# ─── The logical clock ────────────────────────────────

# "At server startup the logical clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_START = "2026-08-01T00:00:00Z"

# ─── Identifiers ──────────────────────────────────────

# A well-formed UUID that names nothing, for the existence gates.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

# ─── Common-field expectations ────────────────────────

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
# The OptionPayment ledger row "carries only id and created_at".
LEDGER_ROW_FIELDS = ("id", "created_at")
LEDGER_ROW_FORBIDDEN_FIELDS = ("updated_at", "version")

# ─── Pagination ───────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Enumerations ─────────────────────────────────────

ENTITY_TYPES = ["INDIVIDUAL", "TRUST", "LLC", "PARTNERSHIP"]
LANDOWNER_STATUSES = ["PROSPECT", "ENGAGED", "UNDER_OPTION", "UNDER_LEASE"]

TITLE_CONDITION_GRADES = ["A", "B", "C", "D"]
PARCEL_STATUSES = ["SCREENING", "QUALIFIED", "OPTIONED", "LEASED", "DISQUALIFIED"]
SCREEN_MODES = ["DESKTOP", "FIELD_VERIFIED"]
SCREENING_TIERS = ["PRIORITY", "STANDARD", "DEFERRED", "REJECTED"]
PROHIBITED_ZONING_CODES = ["RES1", "CONS1"]

SETBACK_RULE_TYPES = ["PROPERTY_LINE", "OCCUPIED_DWELLING", "PUBLIC_ROAD", "WETLAND"]

CONSENT_STATUSES = ["REQUESTED", "GRANTED", "REVOKED", "EXPIRED"]
DEFAULT_CONSENT_EXPIRY_DAYS = 60
MIN_CONSENT_EXPIRY_DAYS = 1
MAX_CONSENT_EXPIRY_DAYS = 365

CURATIVE_ITEM_TYPES = [
    "MINERAL_SEVERANCE",
    "MORTGAGE_SUBORDINATION",
    "ACCESS_EASEMENT_GAP",
    "TAX_LIEN",
    "HEIRSHIP_GAP",
]
CURATIVE_SEVERITIES = ["BLOCKING", "MATERIAL", "ADVISORY"]
CURATIVE_STATUSES = ["BLOCKED", "OPEN", "CLEARED", "WAIVED"]
MAX_WAIVED_BLOCKING_PER_PARCEL = 1

OPTION_STATUSES = [
    "DRAFT",
    "SENT",
    "COUNTERED",
    "REVISED",
    "ACCEPTED",
    "EXECUTED",
    "EXERCISED",
    "EXPIRED",
    "WITHDRAWN",
]
RENT_STRUCTURE_TYPES = ["PER_ACRE", "ROYALTY_HYBRID"]
ESCALATOR_MODES = ["SIMPLE", "COMPOUND"]
MIN_OPTION_TERM_DAYS = 1
MAX_OPTION_TERM_DAYS = 1825
MAX_EXTENSION_COUNT_ALLOWED = 3
MAX_ROYALTY_RATE_BPS = 2000
MAX_ESCALATOR_PCT_BPS = 1000
MAX_NEGOTIATION_ROUNDS = 3

COUNTERABLE_TERMS = [
    "option_fee_per_acre_cents",
    "extension_fee_per_acre_cents",
    "base_rent_per_acre_cents",
    "royalty_rate_bps",
    "escalator_pct_bps",
    "escalator_mode",
    "option_term_days",
]
# A revision may overwrite the same seven terms "plus one more the counter could not".
REVISABLE_TERMS = COUNTERABLE_TERMS + ["rent_structure_type"]

PAYMENT_KINDS = ["INITIAL_OPTION_FEE", "EXTENSION_FEE", "REFUND_REVERSAL"]
LEDGER_DIRECTIONS = ["DEBIT_DEVELOPER", "CREDIT_DEVELOPER"]

CORRIDOR_STATUSES = ["PLANNED", "PERMITTED"]
VOLTAGE_CLASSES = ["COLLECTION_34_5KV", "GENTIE_138KV", "GENTIE_345KV"]
DEFAULT_BUFFER_M = 50
MAX_BUFFER_M = 500

CROSSING_KINDS = ["COLLECTION_LINE", "INTERCONNECTION_ROUTE", "ACCESS_ROAD"]
CROSSING_STATUSES = ["PROPOSED", "GRANTED"]

BOOKING_PURPOSES = ["TITLE_SURVEY", "GEOTECH", "ENV_SURVEY", "CONSTRUCTION_STAGING"]
BOOKING_STATUSES = ["BOOKED", "COMPLETED", "CANCELLED"]
MIN_CREW_COUNT = 1
MAX_CREW_COUNT = 3
PARCEL_MAX_CONCURRENT_CREWS = 3

LEASE_RENT_STATUSES = ["PENDING_FIRST_RENT", "CURRENT", "DELINQUENT"]
LEASE_RECORDING_STATUSES = ["UNRECORDED", "MEMO_SUBMITTED", "RECORDED"]
LEASE_TERM_YEARS = 35

RENT_VARIANTS = ["PROVISIONAL", "FINAL_AS_BUILT"]
INVOICE_STATUSES = ["DRAFT", "ISSUED", "PAID", "VOID"]
MIN_PERIOD_YEAR = 1
MAX_PERIOD_YEAR = 35

# ─── Acreage derivation ───────────────────────────────

# "a slope of 5.0 percent or less excludes nothing ... greater than 15.0 percent
#  carries a rate of one half"
SLOPE_TIERS = [(5.0, 0.00), (10.0, 0.10), (15.0, 0.25)]
SLOPE_RATE_ABOVE_TOP_TIER = 0.50

# "a granted consent buys back eighty percent of the rule's encumbrance"
CONSENT_RELEASE_FRACTION = 0.80

# ─── Screening ────────────────────────────────────────

INTERCONNECT_POINTS_PER_KM = 8
RESOURCE_SCORE_MULTIPLIER = 250
BUILDABILITY_POINTS_PER_SLOPE_PCT = 4
TITLE_SUB_SCORES = {"A": 100, "B": 80, "C": 55, "D": 20}
TITLE_GRADE_LADDER = ["A", "B", "C", "D"]

SCREENING_WEIGHT_INTERCONNECT = 0.30
SCREENING_WEIGHT_RESOURCE = 0.25
SCREENING_WEIGHT_BUILDABILITY = 0.20
SCREENING_WEIGHT_TITLE = 0.25

TIER_PRIORITY_MIN = 82.00
TIER_STANDARD_MIN = 65.00
TIER_DEFERRED_MIN = 45.00

# ─── Qualification ────────────────────────────────────

MIN_BUILDABLE_ACRES = 80.00
QUALIFYING_TIERS = ["PRIORITY", "STANDARD"]

# ─── Option fees ──────────────────────────────────────

EXTENSION_TERM_DAYS = 180
EXTENSION_STEP_UP_FACTOR = 1.15

# ─── Decommissioning security ─────────────────────────

SECURITY_PER_ACRE_CENTS = 50000
SECURITY_TIER_1_CENTS = 5000000
SECURITY_TIER_2_CENTS = 15000000
ADMIN_RATE_BPS_BAND_1 = 600
ADMIN_RATE_BPS_BAND_2 = 450
ADMIN_RATE_BPS_BAND_3 = 300

# ─── Crossing compensation ────────────────────────────

CROSSING_RATE_CENTS_PER_M = {
    "COLLECTION_LINE": 1800,
    "INTERCONNECTION_ROUTE": 3400,
    "ACCESS_ROAD": 900,
}
LONG_OCCUPANCY_FREE_DAYS = 30
LONG_OCCUPANCY_BPS_PER_DAY = 50
LONG_OCCUPANCY_BPS_CAP = 2500

# ─── Rent ─────────────────────────────────────────────

RENT_REFERENCE_PRICE_CENTS_PER_MWH = 4200
INVOICE_NET_DAYS = 45

# ─── Pinned scenario literals reused across the suite ─

# The canonical Caprock jurisdiction and its three published ordinances.
CAPROCK_COUNTY_FIPS = "48453"
CAPROCK_RATES = {
    "PROPERTY_LINE": 0.06,
    "OCCUPIED_DWELLING": 0.10,
    "PUBLIC_ROAD": 0.04,
}
