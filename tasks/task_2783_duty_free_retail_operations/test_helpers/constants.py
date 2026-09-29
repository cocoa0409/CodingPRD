"""Domain constants taken verbatim from the PRD.

Every literal here is stated in the PRD; nothing is inferred. Tests import from
this module instead of repeating magic numbers.
"""

# --- The logical clock (PRD 2.4) -------------------------------------------
# "a server-held logical clock, which starts at exactly `2026-08-01T00:00:00Z`
# when the service boots and only ever moves when a `TerminalAdmin` drives it."
CLOCK_START = "2026-08-01T00:00:00Z"

# --- Money and basis points (PRD 2.6) --------------------------------------
# "All duty rates, tax rates, rent percentages, nationality shares and statutory
# tolerances are expressed in basis points, where 10000 basis points is one whole"
BPS_DENOMINATOR = 10000

# --- Sealed bags (PRD 3.6) -------------------------------------------------
# "`expires_at` is the itinerary's `departure_utc` advanced by the seal validity
# period of 96 hours"
SEAL_VALIDITY_HOURS = 96

# --- Traveller nationality mix (PRD 3.2) -----------------------------------
# "over a rolling window of the last 30 days measured from the current logical clock"
NATIONALITY_MIX_WINDOW_DAYS = 30
# "`required_nationality_share_bps` ... defaults to 1500 basis points"
DEFAULT_REQUIRED_NATIONALITY_SHARE_BPS = 1500

# --- Terminal defaults (PRD 3.1) -------------------------------------------
# "`sealed_bag_regime`, either `ICAO_STEB` or `NONE`, which defaults to `ICAO_STEB`"
DEFAULT_SEALED_BAG_REGIME = "ICAO_STEB"
# "`liquid_limit_ml` ... must not be negative and defaults to 1000"
DEFAULT_LIQUID_LIMIT_ML = 1000

# --- Customs audits (PRD 3.9) ----------------------------------------------
# "The statutory tolerance is 2 percent of the frozen snapshot - the snapshot
# multiplied by 200 basis points, divided by 10000 and floored"
SHRINKAGE_TOLERANCE_BPS = 200
# "the multiplier is 2 when the audit's `round_count` is at least 3, and 1 otherwise"
AUDIT_PENALTY_ROUND_THRESHOLD = 3
AUDIT_PENALTY_MULTIPLIER = 2

# --- Concession settlement (PRD 3.10) --------------------------------------
# "the difference between `period_end_utc` and `period_start_utc` in seconds,
# divided by 86400 seconds - one day - and floored"
SECONDS_PER_DAY = 86400
# "a final rent of at least 5,000,000 cents ... earns 400 basis points, a final
# rent of at least 2,000,000 cents ... earns 250 basis points, and anything below
# that earns 100 basis points"
MARKETING_TIER_1_FLOOR_CENTS = 5_000_000
MARKETING_TIER_1_BPS = 400
MARKETING_TIER_2_FLOOR_CENTS = 2_000_000
MARKETING_TIER_2_BPS = 250
MARKETING_TIER_3_BPS = 100

# --- Pre-orders (PRD 3.8) --------------------------------------------------
# "whose window comes within one day of the requested one"
RESERVATION_BUFFER_HOURS = 24

# --- Pagination (PRD 2.3) --------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
MIN_PAGE_LIMIT = 1

# --- Enumerations ----------------------------------------------------------
CATEGORIES = ("LIQUOR", "TOBACCO", "FRAGRANCE", "CONFECTIONERY", "ELECTRONICS")
SEALED_BAG_REGIMES = ("ICAO_STEB", "NONE")
BRAND_STATUSES = ("ACTIVE", "SUSPENDED")
ASSORTMENT_STATUSES = ("PENDING", "LISTED", "DELISTED")
GRANT_SCOPES = ("TERMINAL_EXCLUSIVE", "CATEGORY_PREFERRED")
GRANT_STATUSES = ("ACTIVE", "REVOKED")
ALLOWANCE_RULE_STATUSES = ("ACTIVE", "SUPERSEDED")
MANUAL_MOVEMENT_TYPES = ("RECEIPT", "AUDIT_ADJUSTMENT")
SYNTHESISED_MOVEMENT_TYPES = (
    "SALE_ISSUE",
    "RESERVATION_HOLD",
    "RESERVATION_RELEASE",
    "SHRINKAGE_WRITE_OFF",
    "REVERSAL",
)
MOVEMENT_AFFECTS = ("ON_HAND", "RESERVED")
SOURCE_REF_TYPES = ("SALE", "PRE_ORDER", "CUSTOMS_AUDIT", "MANUAL", "REVERSAL")
SCAN_STATUSES = ("UNSCANNED", "SCANNED", "AMENDED")
SALE_CHANNELS = ("IN_STORE", "PRE_ORDER")
FULFILLMENT_STATUSES = ("CART", "ELIGIBILITY_CLEARED", "PICKED_UP", "VOIDED")
DUTY_STATUSES = ("SUSPENDED", "DUTY_LIABLE", "EXEMPT_CONFIRMED", "REVERSED")
ELIGIBILITY_VARIANTS = ("SUSPENDED_ESTIMATE", "EXEMPT_CONFIRMED_FINAL")
SEALED_BAG_STATUSES = ("ISSUED", "INTACT_VERIFIED", "TAMPERED", "VOIDED")
SEALED_BAG_OUTCOMES = ("INTACT", "TAMPERED")
PREORDER_PROGRAMS = ("PICKUP_ON_DEPARTURE", "PICKUP_ON_RETURN")
PREORDER_STATUSES = ("RESERVED", "CONVERTED", "CANCELLED", "RELEASED")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")
RENT_BASES = ("PERCENTAGE", "MINIMUM_GUARANTEE")
AUDIT_STATUSES = ("DRAFT", "SUBMITTED", "INFO_REQUESTED", "CLOSED_CLEAN", "CLOSED_ASSESSED")

# --- Non-existent identifiers (all syntactically valid UUIDs) --------------
MISSING_UUIDS = {
    "terminal": "00000000-0000-4000-8000-000000000001",
    "brand": "00000000-0000-4000-8000-000000000002",
    "product": "00000000-0000-4000-8000-000000000003",
    "grant": "00000000-0000-4000-8000-000000000004",
    "allowance_rule": "00000000-0000-4000-8000-000000000005",
    "stock_item": "00000000-0000-4000-8000-000000000006",
    "movement": "00000000-0000-4000-8000-000000000007",
    "itinerary": "00000000-0000-4000-8000-000000000008",
    "sale": "00000000-0000-4000-8000-000000000009",
    "sale_line": "00000000-0000-4000-8000-00000000000a",
    "sealed_bag": "00000000-0000-4000-8000-00000000000b",
    "pre_order": "00000000-0000-4000-8000-00000000000c",
    "agreement": "00000000-0000-4000-8000-00000000000d",
    "audit": "00000000-0000-4000-8000-00000000000e",
}
