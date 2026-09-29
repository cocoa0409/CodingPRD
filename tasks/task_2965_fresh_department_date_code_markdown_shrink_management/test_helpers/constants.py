"""Domain thresholds and reusable test literals taken from the PRD."""

# --------------------------------------------------------------------------
# Numeric thresholds the PRD states explicitly
# --------------------------------------------------------------------------

THRESHOLDS = {
    # The cost floor is 40 percent of the item's unit_cost_cents, rounded half up.
    "COST_FLOOR_PCT_OF_UNIT_COST": 40,
    # Shrink and cost-of-goods lines carry a 3.5 percent waste-handling surcharge.
    "WASTE_HANDLING_SURCHARGE_PCT": 3.5,
    # A scan-price overcharge of at least this many cents withdraws the lot.
    "SCAN_ENFORCEMENT_CENTS": 25,
    # Sell-through shortfall is divided by this many percentage points per step.
    "SELL_THROUGH_STEP_PCT": 20,
    # Promotional lift once a label reaches APPLIED: one tenth of quantity_on_hand.
    "PROMO_LIFT_FRACTION": 0.10,
    # Velocity multipliers by markdown_policy_profile.
    "VELOCITY_STANDARD": 1.00,
    "VELOCITY_AGGRESSIVE": 1.25,
    "VELOCITY_CONSERVATIVE": 0.80,
    # Donation window: opens 48 hours before sell_by_at, closes at sell_by_at.
    "DONATION_WINDOW_HOURS": 48,
    # Dock windows are compared closed with a 30-minute turnaround buffer per side.
    "DOCK_BUFFER_MINUTES": 30,
    # Severity multiplier bands.
    "SEVERITY_TIER_2_HOURS": 48,
    # Severity banding of severity_points_total.
    "SEVERITY_MINOR_MIN_POINTS": 1,
    "SEVERITY_MAJOR_MIN_POINTS": 10,
    "SEVERITY_CRITICAL_MIN_POINTS": 30,
    # Shrink posting delay after verified_at.
    "SHRINK_POSTING_HOURS": 24,
    # Order recommendation horizon and window ceiling.
    "ORDER_HORIZON_DAYS": 3,
    "MAX_WINDOW_DAYS": 31,
    # Department shrink lookback window.
    "SHRINK_LOOKBACK_DAYS": 7,
    # Donation credit tiers, keyed on provisional_value_cents.
    "CREDIT_TIER_1_MAX_CENTS": 50_000,
    "CREDIT_TIER_2_MAX_CENTS": 200_000,
    "CREDIT_RATE_TIER_1_PCT": 62.50,
    "CREDIT_RATE_TIER_2_PCT": 72.50,
    "CREDIT_RATE_TIER_3_PCT": 80,
}

# --------------------------------------------------------------------------
# Server-side defaults the PRD names explicitly
# --------------------------------------------------------------------------

DEFAULTS = {
    "STORE_DOCK_DOOR_CODES": ["D1", "D2", "D3"],
    "STORE_DONATION_PROGRAM_ENABLED": True,
    "STORE_STATUS": "ACTIVE",
    "PARTNER_COLD_CHAIN_CERTIFIED": False,
    "PARTNER_STATUS": "ACTIVE",
    "LADDER_SELL_THROUGH_FLOOR_PCT": 60,
    "LADDER_MAX_TOTAL_DISCOUNT_PCT": 75,
    "DEPARTMENT_PAST_DATE_TOLERANCE_HOURS": 4,
    "DEPARTMENT_SHRINK_BUDGET_PCT": 2.50,
    "DEPARTMENT_MARKDOWN_POLICY_PROFILE": "STANDARD",
    "ITEM_SHELF_LIFE_DAYS": None,
    "ITEM_DONATION_ELIGIBLE": True,
    "ITEM_SAMPLING_ALLOWED": False,
    "ITEM_STATUS": "ACTIVE",
    "LOT_PRODUCTION_BATCH_CODE": None,
    "RECOMMENDATION_METHOD": "CHRONOLOGICAL_ACTUAL",
    "PAGINATION_LIMIT": 10,
    "PAGINATION_OFFSET": 0,
    "PAGINATION_MAX_LIMIT": 100,
}

# The logical clock's startup value.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Ladder rung sets reused across scenarios
# --------------------------------------------------------------------------

MEAT_FOUR_RUNGS = [
    {"days_remaining_max": 3, "discount_pct": 15, "requires_manager_approval": False},
    {"days_remaining_max": 2, "discount_pct": 30, "requires_manager_approval": False},
    {"days_remaining_max": 1, "discount_pct": 50, "requires_manager_approval": True},
    {"days_remaining_max": 0, "discount_pct": 75, "requires_manager_approval": True},
]

MEAT_TWO_RUNGS = [
    {"days_remaining_max": 3, "discount_pct": 15, "requires_manager_approval": False},
    {"days_remaining_max": 1, "discount_pct": 50, "requires_manager_approval": True},
]

DELI_FOUR_RUNGS = [
    {"days_remaining_max": 3, "discount_pct": 20, "requires_manager_approval": False},
    {"days_remaining_max": 2, "discount_pct": 35, "requires_manager_approval": False},
    {"days_remaining_max": 1, "discount_pct": 55, "requires_manager_approval": True},
    {"days_remaining_max": 0, "discount_pct": 70, "requires_manager_approval": True},
]

PRODUCE_TWO_RUNGS = [
    {"days_remaining_max": 2, "discount_pct": 25, "requires_manager_approval": False},
    {"days_remaining_max": 0, "discount_pct": 50, "requires_manager_approval": True},
]

BAKERY_TWO_RUNGS = [
    {"days_remaining_max": 2, "discount_pct": 25, "requires_manager_approval": False},
    {"days_remaining_max": 0, "discount_pct": 50, "requires_manager_approval": True},
]

SEAFOOD_TWO_RUNGS = [
    {"days_remaining_max": 3, "discount_pct": 15, "requires_manager_approval": False},
    {"days_remaining_max": 1, "discount_pct": 40, "requires_manager_approval": True},
]

DAIRY_TWO_RUNGS = [
    {"days_remaining_max": 3, "discount_pct": 15, "requires_manager_approval": False},
    {"days_remaining_max": 1, "discount_pct": 40, "requires_manager_approval": True},
]

# --------------------------------------------------------------------------
# Instants and dates reused across scenarios
# --------------------------------------------------------------------------

CLOCK_REGISTRY_BUILD = "2026-08-10T08:00:00.000Z"
CLOCK_THREE_DAYS_LEFT = "2026-08-12T00:00:00.000Z"

# A path identifier of the right shape that names no row in an empty database.
MISSING_ID = "00000000-0000-4000-8000-000000000000"
MISSING_ID_ALT = "00000000-0000-4000-8000-000000000001"
