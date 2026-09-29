"""Domain thresholds and pinned literals for the Electronic Resource Licensing API.

Every value here is stated in PRD.md; nothing is invented.
"""

# ─── Logical clock ────────────────────────────────────────────────────────────
# "A freshly started server reports a logical current UTC instant of exactly
#  2026-08-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Canonical instants used by the composite fixtures.
ACTIVATION_CLOCK_UTC = "2027-01-02T00:00:00Z"
MID_TERM_CLOCK_UTC = "2027-06-01T00:00:00Z"
POST_DEADLINE_CLOCK_UTC = "2027-11-01T00:00:00Z"
POST_TERM_CLOCK_UTC = "2028-01-02T00:00:00Z"

# ─── Trial evaluation ─────────────────────────────────────────────────────────
TRIAL_COOLDOWN_DAYS = 30
MIN_FEEDBACK_ROWS = 3
ENDORSEMENT_THRESHOLD = 70.00
STAKEHOLDER_QUORUM_GROUPS = 3
QUORUM_PENALTY_FACTOR = 0.90

STAKEHOLDER_WEIGHTS = {
    "FACULTY": 1.5,
    "LIBRARIAN": 1.25,
    "GRADUATE": 1.0,
    "UNDERGRADUATE": 0.5,
}

CRITERION_CODES = [
    "CONTENT_FIT",
    "INTERFACE",
    "ILL_TERMS",
    "TEXT_MINING",
    "ACCESSIBILITY",
    "PRICE_VALUE",
]

STAKEHOLDER_GROUPS = ["FACULTY", "GRADUATE", "UNDERGRADUATE", "LIBRARIAN"]

# ─── Member tier pricing ──────────────────────────────────────────────────────
MIN_MEMBER_PRICE_CENTS = 150000
MAX_MEMBER_SHARE_PCT = 60

FTE_FACTOR_SMALL = 0.60      # fte_count below 5,000
FTE_FACTOR_MEDIUM = 0.85     # 5,000 through 19,999
FTE_FACTOR_LARGE = 1.15      # 20,000 and above
FTE_SMALL_MAX = 5000
FTE_MEDIUM_MAX = 20000

CARNEGIE_FACTORS = {
    "R1": 1.10,
    "R2": 1.00,
    "MASTERS": 0.85,
    "BACCALAUREATE": 0.75,
}
CARNEGIE_CLASSES = ["R1", "R2", "MASTERS", "BACCALAUREATE"]

# ─── Negotiation ──────────────────────────────────────────────────────────────
MAX_NEGOTIATION_ROUNDS = 3

ILL_MODES = ["PROHIBITED", "PRINT_ONLY", "SECURE_ELECTRONIC"]
PERPETUAL_ACCESS_MODES = ["NONE", "POST_CANCELLATION_SUBSET", "FULL_ARCHIVE"]
ACCESSIBILITY_CONFORMANCE = ["NONE", "VPAT_PARTIAL", "WCAG_2_1_AA"]

# ─── Access / authentication ──────────────────────────────────────────────────
MAX_OVERLAPPING_REALM_BINDINGS = 3
DEGRADE_THRESHOLD = 60
ACCESS_HEALTH_MAX = 100
PENALTY_OFF_CAMPUS = 8
PENALTY_ON_CAMPUS = 4
PENALTY_PER_REOPEN = 15
CREDIT_RESOLVED = 5
MAX_CREDITED_DEGRADATIONS = 3
SLA_CREDIT_PCT = 2

AUTH_METHODS = ["IP_RANGE", "EZPROXY", "SHIBBOLETH", "OPENATHENS"]
PROBE_RESULTS = ["PASS", "FAIL_OFF_CAMPUS", "FAIL_ON_CAMPUS"]
SYMPTOM_CODES = [
    "OFF_CAMPUS_DENIED",
    "WALK_IN_BLOCKED",
    "PROXY_LOOP",
    "SAML_ATTRIBUTE_MISSING",
]
ROOT_CAUSE_CODES = [
    "IP_RANGE_STALE",
    "PROXY_MISCONFIGURED",
    "VENDOR_SIDE",
    "ENTITLEMENT_MISSING",
]
REMEDY_CODES = [
    "IP_RANGE_UPDATED",
    "PROXY_FIXED",
    "VENDOR_TICKET_CLOSED",
    "ENTITLEMENT_LOADED",
]

# ─── Cost per use ─────────────────────────────────────────────────────────────
CPU_EXCELLENT_MAX_CENTS = 500     # strictly below 500 => EXCELLENT
CPU_GOOD_MAX_CENTS = 1500         # 500 through below 1500 => GOOD; >= 1500 POOR
CPU_BANDS = ["EXCELLENT", "GOOD", "POOR", "NO_USE"]

LOYALTY_PCT_BY_BAND = {
    "EXCELLENT": 0,
    "GOOD": 2,
    "POOR": 5,
    "NO_USE": 0,
}

# ─── Renewal ──────────────────────────────────────────────────────────────────
VOTE_QUORUM_PCT = 60
RENEWAL_FLOOR_PCT = 50
MIN_ENTITLED_TITLES = 1
RECOMMENDED_ACTIONS = ["RENEW", "CANCEL", "RESTRUCTURE"]
BALLOTS = ["YES", "NO"]

# ─── Archival deposit ─────────────────────────────────────────────────────────
ARCHIVAL_COVERAGE_THRESHOLD_PCT = 95.00
ARCHIVAL_DISCREPANCY_TOLERANCE = 5
ARCHIVAL_AGENCY_CODES = ["PORTICO", "CLOCKSS", "LOCKSS"]

# ─── Pagination ───────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Test data defaults ───────────────────────────────────────────────────────
# A syntactically valid UUID that never names a stored row.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

TEST_DEFAULTS = {
    "VENDOR_NAME": "Atlas Scholarly",
    "SECOND_VENDOR_NAME": "Meridian Press",
    "PRODUCT_NAME": "Atlas Humanities Collection",
    "BASE_LIST_PRICE_CENTS": 10000000,
    "TITLE_COUNT": 400,
    "INFLATION_CAP_PCT": 5.00,
    "CANCELLATION_NOTICE_DAYS": 90,
    "MEMBER_NAME": "Alpha College",
    "FTE_COUNT": 4000,
    "CARNEGIE_CLASS": "BACCALAUREATE",
    "BUDGET_CEILING_CENTS": 9000000,
    "TARGET_TERM_START": "2027-01-01",
    "TARGET_TERM_END": "2027-12-31",
    "ACTIVATION_START_DATE": "2027-01-01",
    "AGREED_PRICE_CENTS": 9000000,
    "AUTH_REALM_CODE": "IP-CAMPUS-1",
    "IP_RANGES": ["203.0.113.0/24"],
}

# The canonical three-band consortium tier schedule of the reference product.
DEFAULT_TIER_BANDS = [
    {"min_participants": 1, "discount_pct": 0},
    {"min_participants": 3, "discount_pct": 10},
    {"min_participants": 5, "discount_pct": 20},
]
