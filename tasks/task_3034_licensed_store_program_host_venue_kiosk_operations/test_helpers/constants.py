"""Domain thresholds and shared constants from the PRD."""

# Logical clock startup default (PRD §2.5).
CLOCK_INITIAL_INSTANT = "2026-09-01T00:00:00Z"

# Certification exam rules (PRD §3.6).
PASS_EXAM_SCORE = 80
AUDIT_ANOMALY_PENALTY = 5

# Supply ordering (PRD §3.5).
VOLUME_DISCOUNT_QTY = 100
VOLUME_DISCOUNT_BPS = 500
BPS_DENOMINATOR = 10000
ORDER_BUDGET_MAX_CENTS = 20000000
MAX_PAR_LEVEL = 1000

# Promotions / price preview (PRD §3.9).
POINT_VALUE_CENTS = 100
REDEEM_CAP_PCT_LICENSED = 50
REDEEM_CAP_PCT_COMPANY = 75

# Inspections (PRD §3.8).
INSPECTION_PASS_SCORE = 85
CATEGORY_FAIL_SCORE = 70
CORRECTIVE_DUE_DAYS = 14
INSPECTION_CATEGORIES = [
    "BEVERAGE_QUALITY",
    "FOOD_SAFETY",
    "BRAND_PRESENTATION",
    "SERVICE_SPEED",
]

# Posture / escalation (PRD §3.6, §3.8).
MIN_CERTIFIED_BARISTAS = 2
MAX_REOPENS = 2
BREACH_SUSPEND_THRESHOLD = 2
CERT_VALIDITY_DAYS = 365

# Loyalty earning (PRD §3.9).
EARN_DIVISOR_CENTS = 200
EARN_RATE_LICENSED = 1
EARN_RATE_COMPANY = 2

# Loyalty event types.
EVENT_EARN = "EARN"
EVENT_REDEEM = "REDEEM"
EVENT_ADJUST = "ADJUST"

# Loyalty store formats.
FORMAT_LICENSED = "LICENSED"
FORMAT_COMPANY_OPERATED = "COMPANY_OPERATED"

# Opaque operator identifiers used by the suite. BrandProgramAdmin and
# BrandInspector ids are never compared to any entity id except where a
# segregation-of-duties rule demands two distinct inspector identities.
INSPECTOR_P = "insp-P"
INSPECTOR_Q = "insp-Q"
INSPECTOR_A = "insp-A"
INSPECTOR_B = "insp-B"
INSPECTOR_Z = "insp-Z"

TEST_DEFAULTS = {
    "TERM_START_DATE": "2026-09-01",
    "TERM_END_DATE": "2027-08-31",
    "ROYALTY_TIERS": [{"threshold_cents": 0, "rate_bps": 300}],
    "VENUE_OPEN": "06:00",
    "VENUE_CLOSE": "22:00",
}
