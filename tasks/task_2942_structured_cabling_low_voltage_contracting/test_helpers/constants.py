"""Numeric constants, patterns and shared literals taken from the PRD.

Every value here restates a figure the PRD fixes; nothing is invented. Tests
import these rather than repeating magic numbers so that a single reading of the
contract governs every assertion.
"""

# ── Envelope and pagination (§2.2, §2.3) ───────────────────────────────────
API_REQUEST_ID_PREFIX = "req_"
RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Logical clock (§2.5) ───────────────────────────────────────────────────
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ── Money and rounding (§2.6) ──────────────────────────────────────────────
DEFAULT_DECIMAL_PLACES = 2
FILL_RATIO_DECIMAL_PLACES = 4

# ── Grounding compliance (§3.1) ────────────────────────────────────────────
MAX_BONDING_AWG = 6
MAX_GROUND_RESISTANCE_MILLIOHMS = 5000
MIN_BRANCH_CIRCUIT_AMPS = 15

# ── Rack elevation geometry (§3.2) ─────────────────────────────────────────
MIN_TOTAL_RU = 1
MAX_TOTAL_RU = 52
RU_CAPACITY_PER_UNIT = 1

# ── Pathway topology (§3.3) ────────────────────────────────────────────────
MAX_PATHWAY_DEPTH = 8

# ── Cable geometry (§3.4) ──────────────────────────────────────────────────
PI = 3.141592653589793
PATCH_CORD_DERATE_FACTOR = 1.2
MAX_PERMANENT_LINK_M = 90.00
MAX_CHANNEL_M = 100.00
FIBER_PERMANENT_FRACTION = 0.9

# ── Identifier patterns (§3.4) ─────────────────────────────────────────────
CLASS_1_PATTERN = r"^[A-Z]{2}[0-9]{2}-[A-Z][0-9]{2}$"
CLASS_2_PATTERN = r"^[0-9]{2}[A-Z]-[A-Z]{2}[0-9]{2}-[A-Z][0-9]{2}$"
SITE_CODE_PATTERN = r"^[A-Z]{2,4}[0-9]{1,2}$"
ROOM_CODE_PATTERN = r"^[A-Z]{2}[0-9]{2}$"
RACK_CODE_PATTERN = r"^[A-Z]$"

# ── Conduit and tray fill (§3.5) ───────────────────────────────────────────
TRAY_FILL_PCT = 50
FILL_PCT_1_CABLE = 53
FILL_PCT_2_CABLES = 31
FILL_PCT_3_PLUS = 40
BEND_DERATE_PCT = 2
BEND_DERATE_THRESHOLD = 2
MIN_FILL_PCT = 25

# ── Power separation (§3.5) ────────────────────────────────────────────────
SEPARATION_FIBER_MM = 0
SEPARATION_SHIELDED_MM = 25
SEPARATION_UNSHIELDED_MM = 50

# ── Field test grading (§3.7) ──────────────────────────────────────────────
IL_BASE_DB = 0.40
IL_PER_M_DB = 0.19
MARGIN_PASS_MIN_DB = 0.0
TESTER_ACCURACY_BAND_DB = 0.5

# ── As-built cost (§3.7) ───────────────────────────────────────────────────
TERMINATION_LABOR_CENTS_PER_END = 4750
TERMINATION_ENDS_PER_LINK = 2
TERMINATION_LABOR_CENTS_PER_LINK = (
    TERMINATION_LABOR_CENTS_PER_END * TERMINATION_ENDS_PER_LINK
)

# ── Occupancy readiness (§3.8) ─────────────────────────────────────────────
OCCUPANCY_READINESS_PCT = 90.00

# ── Moves-adds-changes billing (§3.8) ──────────────────────────────────────
MAC_LABOR_RATE_CENTS_PER_HOUR = 9600
MAC_MIN_BILLABLE_HOURS = 1.0
VOLUME_TIER_1_CENTS = 50000
VOLUME_TIER_2_CENTS = 150000
VOLUME_TIER_0_DISCOUNT_PCT = 0
VOLUME_TIER_1_DISCOUNT_PCT = 5
VOLUME_TIER_2_DISCOUNT_PCT = 10
EXPEDITE_PCT = 15
DEFAULT_MAC_BUDGET_CENTS = 500000

# ── Room change scheduling (§3.8) ──────────────────────────────────────────
ROOM_CHANGEOVER_BUFFER_MINUTES = 30
ROOM_CONCURRENT_CREW_CAPACITY = 2

# ── Warranty coverage (§3.9) ───────────────────────────────────────────────
STANDARD_BASE_YEARS = 15
EXTENDED_BASE_YEARS = 25
REWORK_ATTEMPT_THRESHOLD = 3
REWORK_PENALTY_YEARS = 5
WARRANTY_MIN_YEARS = 10
WARRANTY_ELIGIBILITY_PCT = 100.00

# ── Common resource property names (§2.4) ──────────────────────────────────
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_FIELDS = ("id", "created_at")
