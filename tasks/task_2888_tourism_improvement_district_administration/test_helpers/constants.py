"""Literal constants the PRD fixes for this API.

Everything in this module is quoted from the PRD, so a test that needs a rate,
a cap, a threshold or the clock's origin reads it from here rather than
restating a magic number.
"""

# ---------------------------------------------------------------- clock (2.4)
#: Before any client sets it, the logical clock reads exactly this instant.
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"

# ------------------------------------------------------------ envelope (2.2)
API_REQUEST_ID_PREFIX = "req_"
RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"

# ---------------------------------------------------------- pagination (2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ------------------------------------------------------- district defaults (3.1)
DEFAULT_ASSESSMENT_METHOD = "PCT_OF_ROOM_REVENUE"
DEFAULT_INCLUDED_ZONES = ["ZONE_CORE", "ZONE_PERIMETER"]
DEFAULT_FORMATION_THRESHOLD_PCT = 0.6
DEFAULT_RENEWAL_THRESHOLD_PCT = 0.65
DEFAULT_RENEWAL_HEADCOUNT_THRESHOLD_PCT = 0.5
DEFAULT_TERM_YEARS = 5
DEFAULT_CURRENT_FISCAL_YEAR = 2027
MIN_THRESHOLD_PCT = 0.0001
MAX_THRESHOLD_PCT = 1.0
MIN_TERM_YEARS = 1
MAX_TERM_YEARS = 10
MIN_FISCAL_YEAR = 2020
MAX_FISCAL_YEAR = 2050
MAX_NAME_LENGTH = 120

# --------------------------------------------------- lodging business (3.1)
#: A property with fewer rooms than this is created EXEMPT with exempt_status
#: forced to UNDER_MINIMUM_ROOMS.
MINIMUM_ROOM_COUNT = 5
DEFAULT_EXEMPT_STATUS = "NONE"
DEFAULT_REMITTANCE_FREQUENCY = "MONTHLY"

# ------------------------------------------------------------ petition (3.2)
#: A district needs at least this many assessable businesses to petition.
MINIMUM_ASSESSABLE_POOL = 3
#: A renewal drive may only open inside this many whole days of expiration.
RENEWAL_WINDOW_DAYS = 180

# --------------------------------------------------- assessment period (3.3)
DEFAULT_GRACE_DAYS = 10
MIN_GRACE_DAYS = 0
MAX_GRACE_DAYS = 60
MAX_PERIOD_LABEL_LENGTH = 32
MAX_AMENDMENT_COUNT = 3
#: An amendment's revenue may deviate from the original filing by this share.
AMENDMENT_REVENUE_TOLERANCE = 0.25

# ------------------------------------------- assessment arithmetic (3.3)
ZONE_RATE_PCT_OF_ROOM_REVENUE = {
    "ZONE_CORE": 0.02,
    "ZONE_PERIMETER": 0.0125,
    "OUTSIDE": 0.0,
}
CLASS_MULTIPLIER = {
    "FULL_SERVICE": 1.00,
    "LIMITED_SERVICE": 0.85,
    "BOUTIQUE": 0.90,
    "SHORT_TERM_RENTAL": 1.15,
}
#: Per-night floor on the PCT_OF_ROOM_REVENUE branch, in cents per night.
PER_NIGHT_FLOOR_CENTS = 150
#: Rate on the PER_OCCUPIED_ROOM_NIGHT branch, in cents per occupied night.
PER_OCCUPIED_ROOM_NIGHT_CENTS = 300
TIERED_FLAT_FEE_CENTS = {
    "FULL_SERVICE": 500000,
    "LIMITED_SERVICE": 300000,
    "BOUTIQUE": 350000,
    "SHORT_TERM_RENTAL": 150000,
}
TIERED_ZONE_FACTOR = {
    "ZONE_CORE": 1.0,
    "ZONE_PERIMETER": 0.625,
    "OUTSIDE": 0.0,
}
#: Per-period assessment ceiling applied after the floor comparison.
PERIOD_ASSESSMENT_CEILING_CENTS = 2500000


# --------------------------------------------------------- collections (3.4)
#: A remittance may exceed total_due_cents by at most this many cents.
OVERPAYMENT_TOLERANCE_CENTS = 500000

# --------------------------------------------------------- delinquency (3.5)
PENALTY_RATE = 0.10
DAILY_INTEREST_RATE = 0.0005
#: Outstanding at or above this figure stages the statement LIEN_REFERRED.
LIEN_REFERRAL_THRESHOLD_CENTS = 1000000
STRIKE_STANDING = {0: "GOOD", 1: "WATCH"}  # two or more strikes is SUSPENDED

# ----------------------------------------------------------- work plan (3.7)
ADMIN_SHARE_CAP = 0.15
CONTINGENCY_SHARE_CAP = 0.10
MARKETING_SHARE_FLOOR = 0.60
LODGING_TAX_MATCH_CEILING_SHARE = 0.50
FUNDING_RATIO_FLOOR = 0.9
#: An amendment's total may differ from the stored total by this share.
AMENDMENT_VARIANCE_SHARE = 0.25
MAX_REVISION_COUNT = 3

# ------------------------------------------------------------- program (3.8)
#: Cost-per-room-night ceilings that select the efficiency tier, in cents.
TIER_EFFICIENT_MAX_CENTS = 1500
TIER_STANDARD_MAX_CENTS = 3000
TIER_MARGINAL_MAX_CENTS = 6000
DMO_COST_SHARE = {
    "TIER_EFFICIENT": 0.40,
    "TIER_STANDARD": 0.25,
    "TIER_MARGINAL": 0.10,
    "TIER_UNPRODUCTIVE": 0.00,
}
#: Benchmark cost per room night against which performance_index is measured.
PERFORMANCE_BENCHMARK_CENTS = 2500
MEETS_BENCHMARK_INDEX = 1.0
BELOW_BENCHMARK_INDEX = 0.75
DEFAULT_ATTRIBUTION_METHOD = "DIRECT_PICKUP"

# -------------------------------------------------------- transparency (3.9)
#: Two PUBLIC_MEETING records of one district must be this many whole days apart.
MEETING_SEPARATION_DAYS = 10
#: A notice must be posted at least this many whole days before the meeting.
MEETING_NOTICE_DAYS = 14

# ------------------------------------------------- public reads (2.1)
#: The ten read operations served with no identity headers at all.
PUBLIC_ENDPOINTS = (
    "GET /districts",
    "GET /districts/{id}",
    "GET /districts/{id}/financial-summary",
    "GET /districts/{id}/petition-drives",
    "GET /districts/{id}/annual-work-plans",
    "GET /districts/{id}/transparency-records",
    "GET /petition-drives/{id}",
    "GET /annual-work-plans/{id}",
    "GET /marketing-programs/{id}",
    "GET /transparency-records/{id}",
)
