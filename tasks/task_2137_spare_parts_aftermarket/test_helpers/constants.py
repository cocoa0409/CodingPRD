"""Domain thresholds and numeric constants taken from the PRD's calculations."""

# ─── Logical clock (PRD section 2.4) ────────────────────────────────────────
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# ─── Forecasting (PRD section 3.3) ──────────────────────────────────────────
FORECAST = {
    "ANNUAL_REPLACEMENT_RATE": 0.20,
    "BLEND_WEIGHT_WO": 0.60,
    "DEFAULT_LOOKBACK_DAYS": 365,
}
VALID_HORIZON_MONTHS = (12, 24, 60)

# ─── Criticality classification (PRD section 3.4) ───────────────────────────
CRITICALITY = {
    "DEMAND_SCORE_CAP": 40,
    "DEMAND_UNITS_MULTIPLIER": 2,
    "DOWNTIME_SCORE_MAX": 30,
    "LEAD_TIME_LONG_DAYS": 60,
    "LEAD_TIME_MED_DAYS": 30,
    "COVERAGE_HIGH_UNITS": 4,
    "COVERAGE_MED_UNITS": 2,
    "VITAL_THRESHOLD": 70,
    "ESSENTIAL_THRESHOLD": 40,
}
SERVICE_FACTOR = {"VITAL": 1.65, "ESSENTIAL": 1.28, "DESIRABLE": 0.84}

# ─── Pricing (PRD section 3.5) ──────────────────────────────────────────────
SCARCITY_UPLIFT_PCT = {
    "ACTIVE": 0.00,
    "PHASE_OUT": 0.04,
    "LTB_OPEN": 0.08,
    "LTB_CLOSED": 0.15,
    "OBSOLETE": 0.15,
    "SUPERSEDED": 0.00,
}

# ─── Air-freight decision (PRD section 3.6) ─────────────────────────────────
DOWNTIME_RATE_CENTS_PER_DAY = {"MACHINE_DOWN": 250000, "DEGRADED": 60000, "PLANNED": 0}
AIR = {
    "AIR_RATE_CENTS_PER_KG": 2000,
    "AIR_HANDLING_FEE_CENTS": 10000,
    "AIR_MIN_CHARGE_CENTS": 45000,
    "HAZMAT_SURCHARGE_CENTS": 30000,
    "AIR_APPROVAL_THRESHOLD_CENTS": 100000,
}

# ─── Last-time-buy sizing and windows (PRD section 3.8) ─────────────────────
LTB = {
    "DECAY_FACTOR": 0.85,
    "MAX_COVERAGE_YEARS": 15,
    "MIN_COVERAGE_YEARS": 1,
    "COOLDOWN_DAYS": 30,
}

# ─── Dealer allocation waterfall (PRD section 3.8) ──────────────────────────
TIER_WEIGHT = {"PLATINUM": 50, "GOLD": 30, "SILVER": 10}
ALLOCATION = {
    "INSTALLED_WEIGHT_CAP": 30,
    "INSTALLED_WEIGHT_PER_PAIR": 3,
    "CREDIT_PENALTY": 20,
    "FAIR_SHARE_PCT": 0.50,
}

# ─── Returns: restocking fee and loyalty rebate (PRD section 3.9) ───────────
BASE_FEE_PCT = {
    "WRONG_PART": 0.00,
    "UNUSED_SURPLUS": 0.15,
    "DEFECTIVE": 0.00,
    "CORE_RETURN": 0.00,
}
RETURNS = {
    "AGE_TIER_1_DAYS": 30,
    "AGE_TIER_2_DAYS": 90,
    "AGE_TIER_1_SURCHARGE_PCT": 0.00,
    "AGE_TIER_2_SURCHARGE_PCT": 0.10,
    "AGE_TIER_3_SURCHARGE_PCT": 0.25,
    "OBSOLETE_SURCHARGE_PCT": 0.20,
    "RETURN_WINDOW_DAYS": 180,
    "RESTOCK_FEE_CAP_PCT": 0.50,
    "REBATE_TIER_MID_CENTS": 200000,
    "REBATE_TIER_HIGH_CENTS": 500000,
    "REBATE_MID_PCT": 0.02,
    "REBATE_HIGH_PCT": 0.05,
}

# ─── Backorder promotion sweep (PRD section 3.7) ────────────────────────────
DOWNTIME_RANK = {"MACHINE_DOWN": 0, "DEGRADED": 1, "PLANNED": 2}

# ─── Pagination (PRD section 2.3) ───────────────────────────────────────────
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# ─── Values reused across test setups ───────────────────────────────────────
TEST_DEFAULTS = {
    "UNIT_COST_CENTS": 1333,
    "LEAD_TIME_DAYS": 30,
    "WEIGHT_KG": 1.0,
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "BUILD_REVISION": 100,
    "PRODUCTION_END_DATE": "2025-01-01T00:00:00Z",
    "SUPPORT_END_DATE": "2035-01-01T00:00:00Z",
    "COMMISSION_DATE": "2025-06-01T00:00:00Z",
    "LTB_WINDOW_START": "2026-09-01T00:00:00Z",
    "LTB_WINDOW_END": "2026-10-01T00:00:00Z",
}

# Well-formed UUIDs that resolve to nothing.
UNKNOWN_UUIDS = {
    "part": "00000000-0000-4000-8000-000000000000",
    "model": "00000000-0000-4000-8000-000000000001",
    "installed_unit": "00000000-0000-4000-8000-000000000002",
    "dealer": "00000000-0000-4000-8000-000000000003",
    "work_order": "00000000-0000-4000-8000-000000000004",
    "part_line": "00000000-0000-4000-8000-000000000005",
    "campaign": "00000000-0000-4000-8000-000000000006",
    "allocation_request": "00000000-0000-4000-8000-000000000007",
    "replenishment_order": "00000000-0000-4000-8000-000000000008",
    "return_authorization": "00000000-0000-4000-8000-000000000009",
    "applicability": "00000000-0000-4000-8000-00000000000a",
}
