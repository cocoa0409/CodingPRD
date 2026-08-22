"""Domain thresholds and default test data drawn from the PRD's stated figures."""

# The logical clock reads exactly this instant before any operator repositions it.
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# A convenient position well before every deadline on the standard show calendar.
BASE_CLOCK = "2026-08-10T09:00:00Z"

# The show calendar used by nearly every scenario. Every instant satisfies the
# ordering the DRAFT -> OPEN_FOR_ORDERS transition validates.
SHOW_CALENDAR = {
    "discount_deadline": "2026-09-01T00:00:00Z",
    "advance_warehouse_deadline": "2026-09-10T00:00:00Z",
    "move_in_start": "2026-09-19T08:00:00Z",
    "move_in_end": "2026-09-20T18:00:00Z",
    "show_open": "2026-09-21T09:00:00Z",
    "show_close": "2026-09-23T17:00:00Z",
    "move_out_end": "2026-09-25T18:00:00Z",
}

# Ordered show lifecycle used to walk a show forward one edge at a time.
SHOW_FORWARD_CHAIN = [
    "DRAFT",
    "OPEN_FOR_ORDERS",
    "ADVANCE_CLOSED",
    "MOVE_IN",
    "ON_SITE",
    "MOVE_OUT",
    "CLOSED",
]

# Deadline tier multipliers.
TIER_MULTIPLIERS = {
    "ADVANCE": 1.00,
    "STANDARD": 1.30,
    "ONSITE": 1.65,
}

# Volume-discount bands keyed on subtotal_cents, and service-fee bands keyed on
# discounted_base_cents.
VOLUME_TIERS = [(0, 0.00), (100000, 0.04), (500000, 0.07), (1500000, 0.10)]
FEE_TIERS = [(0, 0.09), (50000, 0.07), (200000, 0.05)]

# Exhibit acquisition quoting.
QUOTE = {
    "RENT_SQFT_CENTS": 2400,
    "RENT_LF_CENTS": 15000,
    "SIGN_RENT_CENTS": 85000,
    "REFURB_LOAD_PCT": 0.12,
    "BUILD_SQFT_CENTS": 7800,
    "BUILD_LF_CENTS": 38000,
    "SIGN_BUILD_CENTS": 210000,
    "DESIGN_FEE_PCT": 0.15,
    "RESIDUAL_PCT": 0.20,
    "PER_SHOW_CARRY_CENTS": 45000,
    "BREAKEVEN_HORIZON": 20,
    "ASSET_WEIGHT_LBS_PER_SQFT": 12,
}

# Drayage.
DRAYAGE = {
    "MIN_BILLABLE_CWT": 2,
    "ADVANCE_RATE_CENTS_PER_CWT": 9800,
    "DIRECT_RATE_CENTS_PER_CWT": 11500,
    "LOOSE_SURCHARGE": 0.30,
    "OT_SURCHARGE": 0.25,
    "LATE_SURCHARGE": 0.35,
}

# Claim settlement.
CLAIM = {
    "TARIFF_CENTS_PER_LB": 30,
    "TARIFF_MAX_PER_CLAIM_CENTS": 5000000,
    "DECLARED_VALUE_DEDUCTIBLE_CENTS": 25000,
    "DEPRECIATION_BY_GRADE": {"A": 0.00, "B": 0.10, "C": 0.25, "D": 0.40},
}

# Lead capture.
LEAD = {
    "DEVICE_FEE_CENTS": 32500,
    "LEAD_OVERAGE_CENTS": 150,
    "DEFAULT_INCLUDED_LEADS": 250,
}

# Cycle budgets and tolerances.
MAX_DESIGN_REVISIONS = 3
MAX_CLAIM_APPEALS = 2
REFURB_OVERRUN_TOLERANCE = 1.20
CONDITION_GRADE_ORDER = ["A", "B", "C", "D"]

# Storage billing.
STORAGE = {
    "DAYS_PER_BILLABLE_MONTH": 30,
    "DEFAULT_FREE_DAYS": 30,
    "DEFAULT_RATE_CENTS_PER_CWT_PER_MONTH": 2200,
}

# Entity defaults asserted by creation tests.
DEFAULTS = {
    "VENUE_STRAIGHT_TIME_START": "08:00",
    "VENUE_STRAIGHT_TIME_END": "16:30",
    "VENUE_MAX_FORKLIFT_LBS": 6000,
    "VENUE_HANGING_SIGN_BOOTH_TYPES": ["ISLAND", "PENINSULA"],
    "VENUE_DOCK_COUNT": 4,
    "JURISDICTION_OVERTIME_MULTIPLIER": 1.5,
    "JURISDICTION_DOUBLETIME_MULTIPLIER": 2.0,
    "JURISDICTION_MIN_CALL_HOURS": 4.0,
    "JURISDICTION_CREW_MAX_SIZE": 8,
    "JURISDICTION_TURNAROUND_BUFFER_MINUTES": 30,
    "WAREHOUSE_STORAGE_RATE": 2200,
    "WAREHOUSE_FREE_DAYS": 30,
    "WAREHOUSE_DOCK_CAPACITY_CWT": 300,
    "EXHIBITOR_CREDIT_LIMIT_CENTS": 500000,
    "DESIGN_EXPECTED_SHOW_COUNT": 1,
    "LICENSE_INCLUDED_LEADS": 250,
}

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 5000000,
    "WAREHOUSE_CAPACITY_CWT": 1000,
    "DOCK_CAPACITY_CWT": 300,
    "BOOTH_SQFT": 400,
    "BOOTH_NUMBER": "1024",
    "STRAIGHT_TIME_RATE_CENTS_PER_HOUR": 14000,
}
