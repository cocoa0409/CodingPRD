"""Domain thresholds and reference figures taken from the PRD's formulas."""

# Rates and thresholds (PRD §2.6, §2.8, §3.x)
BASIS_POINTS_SCALE = 10000

THRESHOLDS = {
    # Destination shortlisting gates (PRD §3.3)
    "MAX_DESTINATION_RISK": 60,
    "MIN_INSPECTION_SCORE": 70,
    # Negotiation ceiling (PRD §3.4)
    "MAX_NEGOTIATION_ROUNDS": 5,
    # Award commitment components (PRD §3.2)
    "GUEST_SHARE_BP": 6250,
    "GRATUITY_BP": 350,
    # Budget posture (PRD §3.7)
    "BUDGET_POSTURE_WATCH_BP": 8500,
    "BUDGET_POSTURE_OVER_BP": 10000,
    # Force-majeure relief (PRD §3.5)
    "FM_NONE_RELIEF_BP": 0,
    "FM_STANDARD_RELIEF_BP": 2500,
    "FM_EXPANDED_RELIEF_BP": 6000,
    # Taxable award base (PRD §3.9)
    "BUSINESS_PURPOSE_EXCLUSION_BP": 1500,
    # Gross-up (PRD §3.9)
    "FED_SUPPLEMENTAL_BP": 2200,
    "FICA_BP": 765,
    "STATE_TIER_LOW_BP": 300,
    "STATE_TIER_MID_BP": 500,
    "STATE_TIER_HIGH_BP": 700,
    "STATE_TIER_MID_FLOOR_CENTS": 500000,
    "STATE_TIER_HIGH_FLOOR_CENTS": 1500000,
    # Air cost (PRD §3.7)
    "DEVIATION_FREE_DAYS": 2,
    "DEVIATION_DAY_FEE_CENTS": 9500,
    "DEVIATION_MAX_DAYS_TOTAL": 7,
    "CHANGE_FEE_BASE_CENTS": 12500,
    "CHANGE_FEE_ESCALATOR_BP": 5000,
    "CHANGE_FEE_CAP_BP": 4000,
    "UPGRADE_STEP_ECONOMY_CENTS": 0,
    "UPGRADE_STEP_PREMIUM_ECONOMY_CENTS": 48000,
    "UPGRADE_STEP_BUSINESS_CENTS": 165000,
    # Activity conflict buffer (PRD §3.8)
    "TRANSFER_BUFFER_MINUTES": 45,
}

UPGRADE_LADDER_CENTS = {
    "ECONOMY": 0,
    "PREMIUM_ECONOMY": 48000,
    "BUSINESS": 165000,
}

FORCE_MAJEURE_RELIEF_BP = {
    "NONE": 0,
    "STANDARD": 2500,
    "EXPANDED": 6000,
}

# The logical clock's fixed start instant (PRD §2.5).
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Reference default payload values used by the factories and fixtures.
TEST_DEFAULTS = {
    "PROGRAM_NAME": "FY26 Presidents Circle",
    "FISCAL_YEAR": 2026,
    "QUALIFICATION_METRIC": "NET_REVENUE_CENTS",
    "SALES_PERIOD_START": "2026-01-01T00:00:00Z",
    "SALES_PERIOD_END": "2026-06-30T00:00:00Z",
    "BUDGET_TOTAL_CENTS": 50_000_000,
    "PER_PERSON_COST_CENTS": 400_000,
    "RISK_SCORE": 30,
    "INSPECTION_SCORE": 85,
    "CITY": "Lisbon",
    "COUNTRY_CODE": "PT",
    "AIR_GATEWAY_CODE": "LIS",
    "SUPPLIER_NAME": "Tivoli Palacio",
    "ROOM_BLOCK_COUNT": 12,
    "CONTRACTED_NIGHTS": 10,
    "STAY_START_AT": "2026-11-01T00:00:00Z",
    "STAY_END_AT": "2026-11-11T00:00:00Z",
    "NIGHTLY_RATE_CENTS": 38_500,
    "ATTRITION_ALLOWANCE_BP": 2000,
    "ARRIVAL_DATE": "2026-11-02T00:00:00Z",
    "DEPARTURE_DATE": "2026-11-06T00:00:00Z",
    "ACTIVITY_START_AT": "2026-11-03T09:00:00Z",
    "ACTIVITY_END_AT": "2026-11-03T13:00:00Z",
    "TIER_BUDGET_PER_QUALIFIER_CENTS": 5_000_000,
    "BASELINE_METRIC": 180_000_000,
    "ACTUAL_METRIC": 260_000_000,
}

# Distinct operator identities. Every owner the PRD requires to be distinct gets
# its own X-User-ID (PRD §2.9 compares user identities, not roles).
USER_IDS = {
    "PROGRAM_DIRECTOR": "pd-01",
    "SOURCING_MANAGER": "sm-01",
    "SOURCING_MANAGER_ALT": "sm-02",
    "CONTRACT_APPROVER": "ca-01",
    "CONTRACT_APPROVER_ALT": "ca-02",
    "SALES_OPS_ANALYST": "an-01",
    "TRAVEL_DESK": "td-01",
    "TAX_OFFICER": "tax-01",
    "TAX_OFFICER_ALT": "tax-02",
}
