"""Domain thresholds and defaults — numeric constants from the PRD.

Every value below is stated in PRD prose (§2.3, §2.4, §3.1, §3.3, §3.4,
§3.5, §3.6, §3.8); this module is the single place tests read them from.
"""

# --- Logical clock (PRD §2.4: startup default, never wall-clock) ---
CLOCK_START = "2026-09-01T00:00:00Z"
CLOCK_START_MONTH = "2026-09"

# --- Age bands (PRD §3.5: INFANT 0-11, TODDLER 12-23, TWO 24-35,
#     THREE 36-47, FOUR 48-59; age_months >= 60 mails nothing) ---
AGE_BANDS = ["INFANT", "TODDLER", "TWO", "THREE", "FOUR"]
BAND_EDGES_MONTHS = [0, 12, 24, 36, 48, 60]
MAX_MAILING_AGE_MONTHS = 59  # PRD §3.3: age at registration month must be <= 59

# --- Undeliverable-mail threshold (PRD §3.4: counter reaching two
#     auto-unenrolls) ---
RETURN_AUTO_UNENROLL_THRESHOLD = 2

# --- Volume pricing (PRD §3.6: lower bounds inclusive) ---
TIER_1_UNIT_CENTS = 210   # quantity < 5000
TIER_2_UNIT_CENTS = 185   # quantity >= 5000
TIER_3_UNIT_CENTS = 160   # quantity >= 20000
TIER_4_UNIT_CENTS = 140   # quantity >= 50000
TIER_2_MIN_QTY = 5000
TIER_3_MIN_QTY = 20000
TIER_4_MIN_QTY = 50000
PLATE_FEE_CENTS = 25000
PLATE_FEE_WAIVER_QTY = 20000  # waived at qty >= 20000 OR is_reprint
REPRINT_DISCOUNT_NUM = 9      # reprint pays nine-tenths of tier price,
REPRINT_DISCOUNT_DEN = 10     # rounded half up to a whole cent
PRESS_MONTHLY_CAPACITY = 400000  # per production month; equality allowed

# --- Per-item book cost (PRD §3.8: floor(total_cents / quantity) + handling) ---
HANDLING_CENTS_PER_BOOK = 35

# --- State program funding (PRD §2.6 / §3.1) ---
FUNDING_SHARE_BP_MAX = 10000
DEFAULT_MAX_STATE_SHARE_PER_BOOK_CENTS = 300  # server default when omitted

# --- Pagination (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Invoice pricing variant pinned on issued invoices (PRD §3.8) ---
PRICING_VARIANT_PER_LINE = "PER_LINE"

# --- Shared fixture geography / window defaults (PRD-consistent; these are
#     test data, not rules — chosen so the default logical month 2026-09 is
#     fully covered and default titles cover default wave month 2026-10) ---
DEFAULT_STATE_CODE = "TN"
DEFAULT_PROGRAM_NAME = "TN Imagination Partnership"
DEFAULT_FUNDING_SHARE_BP = 4925
DEFAULT_AFFILIATE_NAME = "Nashville Books Together"
DEFAULT_POSTAL_PREFIXES = ["372", "370"]
DEFAULT_CONTACT_EMAIL = "coord@nbt.org"
DEFAULT_AGREEMENT_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
DEFAULT_AGREEMENT_EFFECTIVE_TO = "2028-01-01T00:00:00Z"
DEFAULT_FUNDRAISING_COMMITMENT_CENTS = 5_000_000
DEFAULT_POPULATION_YEAR = 2026
DEFAULT_ELIGIBLE_POPULATION = 10000
DEFAULT_WAVE_MONTH = "2026-10"
DEFAULT_TITLE_FROM_MONTH = "2026-01"
DEFAULT_TITLE_UNTIL_MONTH = "2027-12"
DEFAULT_PRINT_QUANTITY = 6000

# --- Advisory committee member identities (opaque role; segregation of
#     duties requires distinct proposer / approver ids, PRD §3.5) ---
ACM_PROPOSER_ID = "acm-ada"
ACM_APPROVER_ID = "acm-ben"
ACM_THIRD_ID = "acm-cid"

# --- A syntactically valid UUID that no server will have allocated ---
BOGUS_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
