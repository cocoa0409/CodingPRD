"""Named domain thresholds and canonical fixture literals.

Every value here is quoted from the PRD; the section that fixes it is named
in the trailing comment so a reader can check the number without leaving the
file.
"""

# ─── Clock (PRD §2.4) ────────────────────────────────────────────────
# Before the first set-clock call the clock reads exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ─── Envelope (PRD §2.2) ─────────────────────────────────────────────
API_REQUEST_ID_PREFIX = "req_"
DEFAULT_LIMIT = 10        # PRD §2.3
MAX_LIMIT = 100           # PRD §2.3
MIN_LIMIT = 1             # PRD §2.3

# ─── Owner capacity scoring (PRD §3.2) ───────────────────────────────
LIQUIDITY_BENCHMARK_AMOUNT = 5_000_000.00
BALANCE_SHEET_BENCHMARK_AMOUNT = 15_000_000.00
PORTFOLIO_LIQUIDITY_RESERVE_PER_UNIT = 250_000.00
CREDIT_SCORE_FLOOR = 500
CREDIT_SCORE_SPAN = 300
CAPACITY_WEIGHT_LIQUIDITY = 0.45
CAPACITY_WEIGHT_BALANCE_SHEET = 0.30
CAPACITY_WEIGHT_CREDIT = 0.25
EXPERIENCE_BONUS_PER_UNIT = 1.5
EXPERIENCE_BONUS_UNIT_CAP = 5
CAPACITY_BAND_STRONG = 75.00
CAPACITY_BAND_ADEQUATE = 55.00
CAPACITY_SCORE_CAP = 100.00

# ─── Market impact study (PRD §3.4) ──────────────────────────────────
CLAIM_WINDOW_DAYS = 21
SUSTAINED_CLAIM_PENALTY_POINTS = 7.50
VERDICT_ENCROACHMENT_CONFIRMED_THRESHOLD = 25.00
VERDICT_MITIGATION_REQUIRED_THRESHOLD = 12.00

# ─── License drafting (PRD §3.6) ─────────────────────────────────────
CONVERSION_ADJUSTMENT_COMPETITOR = 0.75
CONVERSION_ADJUSTMENT_INDEPENDENT = 0.25
CONVERSION_ADJUSTMENT_OUR_BRAND = 0.00
CAPACITY_DISCOUNT_STRONG_PORTFOLIO = 0.50
CAPACITY_DISCOUNT_STRONG_SINGLE = 0.25
CAPACITY_DISCOUNT_PORTFOLIO_UNIT_THRESHOLD = 3
ROYALTY_RATE_FLOOR_PCT = 3.50
ROYALTY_RATE_CAP_PCT = 7.00
MARKETING_SURCHARGE_PCT = 0.50
MARKETING_SURCHARGE_IMPACT_THRESHOLD = 12.00
MARKETING_FUND_RATE_CAP_PCT = 3.00
MINIMUM_TERM_YEARS = 15
LIQUIDATED_DAMAGES_CAP_MONTHS = 36

# ─── Property improvement plan (PRD §3.7) ────────────────────────────
KEY_MONEY_BAND_HIGH_COST_PER_ROOM = 25_000.00
KEY_MONEY_BAND_HIGH_PCT = 10
KEY_MONEY_BAND_MID_COST_PER_ROOM = 12_000.00
KEY_MONEY_BAND_MID_PCT = 6
KEY_MONEY_BAND_LOW_PCT = 0
FRANCHISOR_KEY_MONEY_CAP = 250_000.00
ESCALATION_NET_COST_PER_ROOM_THRESHOLD = 20_000.00

PRIORITY_DAY_BUDGET = {
    "CRITICAL": 90,
    "MAJOR": 180,
    "MINOR": 270,
}
CATEGORY_DAY_BUDGET = {
    "LIFE_SAFETY": 45,
    "TECHNOLOGY": 120,
    "FOOD_BEVERAGE": 180,
    "GUESTROOM": 210,
    "EXTERIOR": 240,
}

EXTENSION_REQUEST_LIMIT = 2
EXTENSION_LINE_DAY_POOL = 60
EXTENSION_PLAN_DAY_POOL = 120
PIP_CURE_PERIOD_DAYS = 30

# ─── Fee ledger (PRD §3.8) ───────────────────────────────────────────
ROYALTY_TIER_ONE_CEILING = 200_000.00
ROYALTY_TIER_TWO_CEILING = 500_000.00
ROYALTY_TIER_TWO_PREMIUM_PCT = 0.50
ROYALTY_TIER_THREE_PREMIUM_PCT = 1.00
RESERVATION_FEE_RATE_PCT = 1.75

# ─── Quality assurance (PRD §3.8) ────────────────────────────────────
QA_WEIGHT_CLEANLINESS = 0.30
QA_WEIGHT_CONDITION = 0.25
QA_WEIGHT_BRAND_STANDARD = 0.30
QA_WEIGHT_GUEST_EXPERIENCE = 0.15
QA_CRITICAL_DEFECT_PENALTY = 5.00
QA_GRADE_PASS_THRESHOLD = 85.00
QA_GRADE_CONDITIONAL_THRESHOLD = 70.00
QA_CURE_DAYS_CONDITIONAL = 60
QA_CURE_DAYS_FAIL = 30
MIN_INSPECTION_GAP_DAYS = 90
CONSECUTIVE_QA_FAILURE_LIMIT = 3

# ─── Consent, transfer and termination (PRD §3.9) ────────────────────
CONSENT_FEE_PER_ROOM = 750.00
CONSENT_FEE_FLOOR = 75_000.00
REFINANCE_CONSENT_FEE = 15_000.00
NON_COMPLIANCE_SURCHARGE = 25_000.00
DISCOUNTED_PV_MONTHLY_RATE = 1.0050
DE_IDENTIFICATION_WINDOW_DAYS = 30
DE_IDENTIFICATION_BREACH_PENALTY = 50_000.00
DE_IDENTIFICATION_ITEM_CODES = [
    "SIGNAGE",
    "INTERIOR_BRANDING",
    "DIGITAL_LISTINGS",
    "LINENS_AND_COLLATERAL",
    "RESERVATION_CODES",
]

# ─── Canonical fixture literals ──────────────────────────────────────
# The recurring brand under test: an UPSCALE brand whose five-mile ring and
# eighty-room floor make both the impact study and the room-minimum gate
# reachable from a single 120-room applicant property.
SOLARIS_BRAND = {
    "code": "SOLARIS",
    "name": "Solaris Collection",
    "tier": "UPSCALE",
    "base_royalty_rate_pct": 5.00,
    "marketing_fund_rate_pct": 2.50,
    "protected_radius_miles": 5.00,
    "min_room_count": 80,
    "standard_term_years": 20,
}

# A STRONG, four-unit owner: capacity 96.67 STANDALONE and 100.00
# PORTFOLIO_ADJUSTED, so the live-band gate on execution always clears.
STRONG_OWNER = {
    "legal_name": "Harbor Point Hospitality LP",
    "contact_email": "deals@harborpointhosp.example",
    "liquid_assets_amount": 6_000_000.00,
    "net_worth_amount": 18_000_000.00,
    "credit_score": 760,
    "existing_units_count": 4,
}

# The recurring conversion candidate: 120 rooms, COMPETITOR affiliation,
# twenty-year request effective 2026-10-01.
HARBOR_POINT_APPLICATION = {
    "property_name": "Harbor Point Hotel",
    "market_code": "SEADT",
    "property_x_miles": 0.00,
    "property_y_miles": 0.00,
    "room_count": 120,
    "current_affiliation": "COMPETITOR",
    "building_age_years": 18,
    "requested_term_years": 20,
    "requested_conversion_date": "2026-10-01",
}

DEFAULT_EFFECTIVE_DATE = "2026-10-01"

# The three-package conversion scope used by most plan scenarios:
# 3,120,000.00 total over 120 rooms.
GUESTROOM_SCOPE_LINE = {
    "category": "GUESTROOM",
    "priority": "MAJOR",
    "description": "Guestroom soft goods and case goods replacement",
    "estimated_cost": 2_400_000.00,
}
LIFE_SAFETY_SCOPE_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "CRITICAL",
    "description": "Sprinkler and addressable alarm upgrade",
    "estimated_cost": 480_000.00,
}
EXTERIOR_SCOPE_LINE = {
    "category": "EXTERIOR",
    "priority": "MINOR",
    "description": "Porte-cochere rebuild and signage",
    "estimated_cost": 240_000.00,
}
THREE_LINE_SCOPE = [GUESTROOM_SCOPE_LINE, LIFE_SAFETY_SCOPE_LINE, EXTERIOR_SCOPE_LINE]

# Clock waypoints shared by the multi-stage lifecycle fixtures.
CLOCK_INTAKE = "2026-08-01T00:00:00Z"
CLOCK_REVIEW = "2026-08-05T00:00:00Z"
CLOCK_DECISION = "2026-09-01T00:00:00Z"
CLOCK_DRAFT = "2026-09-05T00:00:00Z"
CLOCK_EXECUTE = "2026-09-10T00:00:00Z"
CLOCK_SCOPE = "2026-09-12T00:00:00Z"
CLOCK_ACCEPT = "2026-10-05T00:00:00Z"
CLOCK_COMPLETE = "2026-10-20T00:00:00Z"
CLOCK_VERIFY = "2026-10-22T00:00:00Z"
CLOCK_OPEN = "2026-11-01T00:00:00Z"
CLOCK_NOVEMBER_REPORT = "2026-12-05T00:00:00Z"
CLOCK_DECEMBER_REPORT = "2027-01-05T00:00:00Z"

# Deadlines the accepted three-line scope produces from 2026-10-05.
#
# PRD §3.7 anchors a scope line's base_due_date on the plan's ``accepted_at``
# -- an instant -- "advanced by that allowance in whole days, preserving the
# time of day exactly as §2.4 requires", and §2.4 names "scope-line due dates"
# among the windows that rule governs.  A due date is therefore a full
# ISO-8601 instant carrying the acceptance time of day (00:00:00.000Z here),
# not a bare calendar date.
DUE_DATE_GUESTROOM = "2027-04-03T00:00:00.000Z"    # min(MAJOR 180, GUESTROOM 210)
DUE_DATE_LIFE_SAFETY = "2026-11-19T00:00:00.000Z"  # min(CRITICAL 90, LIFE_SAFETY 45)
DUE_DATE_EXTERIOR = "2027-06-02T00:00:00.000Z"     # min(MINOR 270, EXTERIOR 240)
