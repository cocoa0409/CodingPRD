"""Domain thresholds and canonical scenario data taken from the PRD narratives."""

# Feasibility screening (PRD §3.2)
FEASIBILITY = {
    "STATUTORY_ALWAYS_ALLOWED_SQFT": 800,
    "STATUTORY_SETBACK_FT": 4.0,
    "STATUTORY_MAX_HEIGHT_FT": 16.0,
    "AMP_TIER_1_MAX_SQFT": 750,
    "AMP_TIER_2_MAX_SQFT": 1000,
    "EXISTING_DWELLING_LOAD_AMPS": 100,
    "WATER_METER_MIN_IN_SMALL": 0.625,
    "WATER_METER_MIN_IN_LARGE": 0.75,
}

# Separate service versus shared metering (PRD §3.3)
METERING = {
    "SEPARATION_THRESHOLD": 50,
    "SEPARATE_METER_BASE_CENTS": 850_000,
    "SHARED_SUBMETER_CENTS": 220_000,
}

# Permit fee schedule (PRD §3.4)
PERMIT_FEE = {
    "TECH_SURCHARGE_PCT": 0.075,
    "IMPACT_FEE_EXEMPT_SQFT": 750,
    "SCHOOL_FEE_MIN_SQFT": 500,
    "SCHOOL_FEE_RATE_PER_SQFT_CENTS": 452,
}

# Change-order markup tiers and cumulative cap (PRD §3.6)
CHANGE_ORDER = {
    "MARKUP_TIER_1_MAX_PCT": 5.0,
    "MARKUP_TIER_2_MAX_PCT": 15.0,
    "MARKUP_RATE_TIER_1": 0.10,
    "MARKUP_RATE_TIER_2": 0.15,
    "MARKUP_RATE_TIER_3": 0.20,
    "CHANGE_ORDER_CAP_PCT": 25.0,
}

# Financing capacity (PRD §3.5)
FINANCING = {
    "MAX_LTV_PCT": 0.80,
    "CAP_RATE": 0.055,
    "VACANCY_FACTOR": 0.92,
    "EXPENSE_RATIO": 0.35,
    "SOFT_COST_CONTINGENCY_PCT": 0.10,
}

# Rental readiness (PRD §3.9)
RENTAL = {
    "STATE_MIN_ADU_LEASE_DAYS": 30,
    "STR_PERMITTED_MAX_LEASE_DAYS": 7,
}

# Construction windows and inspector slots (PRD §2.10, §3.7)
SCHEDULING = {
    "HABITABILITY_BUFFER_DAYS": 2,
    "OCCUPIED_SHUTOFF_MAX_DAYS": 1,
}

# The logical clock reads exactly this before any operator moves it (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Canonical jurisdictions / parcels / projects used across the suite.
# ---------------------------------------------------------------------------

PLMD_JURISDICTION = {
    "name": "Palmdale",
    "code": "PLMD",
    "local_max_detached_sqft": 1000,
    "local_rear_setback_ft": 4.0,
    "local_side_setback_ft": 4.0,
    "local_max_height_ft": 18.0,
    "plan_check_base_fee_cents": 120_000,
    "plan_check_rate_per_sqft_cents": 90,
    "impact_fee_per_sqft_cents": 800,
    "utility_capacity_fee_cents": 250_000,
    "correction_response_days": 45,
    "separate_meter_required": False,
    "str_min_lease_days": 7,
    "str_prohibited": False,
}

SNVL_JURISDICTION = {
    "name": "Sunnyvale",
    "code": "SNVL",
    "local_max_detached_sqft": 750,
    "local_rear_setback_ft": 10.0,
    "local_side_setback_ft": 5.0,
    "local_max_height_ft": 14.0,
    "plan_check_base_fee_cents": 185_025,
    "plan_check_rate_per_sqft_cents": 137,
    "impact_fee_per_sqft_cents": 1_250,
    "utility_capacity_fee_cents": 415_000,
    "correction_response_days": 60,
    "separate_meter_required": True,
    "str_min_lease_days": 30,
    "str_prohibited": False,
}

# Parcel P2: unoccupied, generous 400 A service and a 1.0 in meter.
P2_PROPERTY = {
    "address_line": "12 Sage Ct",
    "lot_sqft": 8_000,
    "existing_dwelling_sqft": 1_450,
    "electrical_service_amps": 400,
    "existing_water_meter_size_in": 1.0,
    "pre_adu_value_cents": 80_000_000,
    "occupied": False,
    "in_str_overlay": False,
    "existing_mortgage_balance_cents": 60_000_000,
}

# Parcel P1: occupied, tight 200 A service and a 0.75 in meter.
P1_PROPERTY = {
    "address_line": "418 Alder Way",
    "lot_sqft": 6_000,
    "existing_dwelling_sqft": 1_600,
    "electrical_service_amps": 200,
    "existing_water_meter_size_in": 0.75,
    "pre_adu_value_cents": 120_000_000,
    "occupied": True,
    "in_str_overlay": False,
    "existing_mortgage_balance_cents": 45_000_000,
}

# Project B: 767 sqft detached new build on P2.
PROJECT_B = {
    "unit_type": "DETACHED_NEW",
    "proposed_sqft": 767,
    "proposed_height_ft": 16.0,
    "rear_setback_ft": 5.0,
    "side_setback_ft": 5.0,
    "bedrooms": 2,
    "contract_base_price_cents": 24_000_000,
}

# Project A: 800 sqft detached new build on P1.
PROJECT_A = {
    "unit_type": "DETACHED_NEW",
    "proposed_sqft": 800,
    "proposed_height_ft": 16.0,
    "rear_setback_ft": 5.0,
    "side_setback_ft": 4.0,
    "bedrooms": 2,
    "contract_base_price_cents": 28_000_000,
}

ALL_CERTIFICATIONS = ["STRUCTURAL", "ELECTRICAL", "PLUMBING", "ENVELOPE", "FINAL"]
