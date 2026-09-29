"""Domain thresholds and calendar landmarks taken from the PRD's calculations."""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.6)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_ISO_WEEK = "2026-W31"

# The corner/difficulty recipes pin the clock here before every scenario.
PINNED_CLOCK_INSTANT = "2026-09-01T09:00:00Z"
PINNED_CLOCK_ISO_WEEK = "2026-W36"

# ISO Monday for each week label used by the fixtures.
ISO_WEEK_MONDAYS = {
    "2026-W31": "2026-07-27",
    "2026-W36": "2026-08-31",
    "2026-W37": "2026-09-07",
    "2026-W38": "2026-09-14",
    "2026-W39": "2026-09-21",
    "2026-W40": "2026-09-28",
    "2026-W41": "2026-10-05",
    "2026-W42": "2026-10-12",
    "2026-W43": "2026-10-19",
    "2026-W44": "2026-10-26",
}


# --------------------------------------------------------------------------
# Attendance and pressure (PRD §3.4, §3.5)
# --------------------------------------------------------------------------
THRESHOLDS = {
    # Credited days
    "MIN_PRESENCE_MINUTES": 240,
    "MAX_CREDITED_DAYS": 5,
    "WORKING_DAYS_PER_WEEK": 5,
    "WEEK_DATE_SPAN": 7,
    # Severity multipliers by eligibility class
    "SEVERITY_FULLY_REMOTE": 0.0,
    "SEVERITY_HYBRID": 1.0,
    "SEVERITY_ONSITE_REQUIRED": 1.5,
    "CONSECUTIVE_WEEK_WEIGHT": 1.0,
    "PRESSURE_CEILING": 12.00,
    # compliance_state bands
    "COMPLIANT_PRESSURE": 0.00,
    "AT_RISK_UPPER_EXCLUSIVE": 2.00,
    "BREACH_LOWER_INCLUSIVE": 2.00,
    # escalation stage bands
    "STAGE_REFERRED_MIN": 10.00,
    "STAGE_PERFORMANCE_PLAN_MIN": 7.00,
    "STAGE_WRITTEN_WARNING_MIN": 4.00,
    "STAGE_COACHING_MIN": 2.00,
    # Required days by class
    "REQUIRED_DAYS_FULLY_REMOTE": 0,
    "REQUIRED_DAYS_ONSITE_REQUIRED": 5,
    # Seat entitlement tiers (keyed on base_entitlement)
    "BUFFER_TIER_SMALL_MAX_BASE": 10,
    "BUFFER_TIER_SMALL_PCT": 0.20,
    "BUFFER_TIER_MID_MAX_BASE": 25,
    "BUFFER_TIER_MID_PCT": 0.12,
    "BUFFER_TIER_LARGE_PCT": 0.06,
    # Chargeback (PRD §3.8)
    "BASE_SEAT_RATE_CENTS": 4333,
    "BPS_DENOMINATOR": 10000,
    "BPS_FIVE_DAY": 10000,
    "BPS_FOUR_DAY": 9500,
    "BPS_THREE_DAY": 9000,
    "BPS_TWO_OR_FEWER_DAY": 8500,
    # Neighborhood allocation state
    "TIGHT_UTILIZATION_PCT": 90.00,
    # Relocation risk (PRD §3.7)
    "RISK_US_TX": 6,
    "RISK_US_CA": 10,
    "RISK_US_NY": 12,
    "RISK_IE": 18,
    "RISK_IN": 26,
    "RISK_BR": 30,
    "TIER_PUBLIC": 0,
    "TIER_INTERNAL": 8,
    "TIER_CONFIDENTIAL": 18,
    "TIER_RESTRICTED": 30,
    "LICENSING_PENALTY_PER_GAP": 7,
    "LICENSING_PENALTY_CAP": 21,
    "CONTROL_PENALTY_PER_GAP": 9,
    "CONTROL_PENALTY_CAP": 27,
    "NEXUS_CENTS_PER_POINT": 250000,
    "NEXUS_PENALTY_CAP": 12,
    "RISK_SCORE_CEILING": 100,
    "RELOCATION_APPROVAL_CEILING": 60,
    "TAX_NEXUS_BUDGET_CENTS": 5000000,
    # Equity (PRD §3.9)
    "MIN_BAND_POPULATION": 2,
    "MIN_QUALIFYING_BANDS": 2,
}

JURISDICTION_RISK_POINTS = {
    "US_TX": 6,
    "US_CA": 10,
    "US_NY": 12,
    "IE": 18,
    "IN": 26,
    "BR": 30,
}

DATA_TIER_RISK_POINTS = {
    "PUBLIC": 0,
    "INTERNAL": 8,
    "CONFIDENTIAL": 18,
    "RESTRICTED": 30,
}

APPROVED_RESIDENCY_JURISDICTIONS = ["US_CA", "US_TX", "US_NY"]

DISCOUNT_BPS_BY_EXPECTED_DAYS = {
    5: 10000,
    4: 9500,
    3: 9000,
    2: 8500,
    1: 8500,
    0: 8500,
}


# --------------------------------------------------------------------------
# Declared numeric / string ranges (PRD §3.1–§3.9)
# --------------------------------------------------------------------------
RANGES = {
    "days_in_office_floor": (0, 5),
    "badge_weight": (0.00, 1.00),
    "network_weight": (0.00, 1.00),
    "collaboration_target_score": (0.00, 100.00),
    "equity_variance_threshold_pct": (0.00, 100.00),
    "expected_days_in_office_per_week": (0, 5),
    "headcount_planned": (1, 5000),
    "minutes_present": (0, 1440),
    "requested_relief_days": (1, 5),
    "licensing_gap_count": (0, 20),
    "control_gap_count": (0, 20),
    "tax_nexus_registration_cost_cents": (0, 100000000),
    "seat_count": (1, 500),
    "allocated_seats": (1, 500),
    "proposed_days_in_office_delta": (-2, 2),
    "limit": (1, 100),
}

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_DEFAULT_OFFSET = 0


# --------------------------------------------------------------------------
# Test defaults used by the factories and fixtures
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "CYCLE_EFFECTIVE_FROM": "2026-08-01",
    "CYCLE_EFFECTIVE_TO": "2026-12-31",
    "TENURE_START_DATE": "2024-01-15",
    "HOME_TIMEZONE": "Europe/Dublin",
    "SITE_CODE": "DUB-01",
    "FULL_DAY_MINUTES": 480,
}

# UUIDs that never resolve to a stored row.
UNKNOWN_POLICY_CYCLE_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_TEAM_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_EMPLOYEE_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_CLASSIFICATION_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_ATTENDANCE_WEEK_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_SIGNAL_ID = "00000000-0000-4000-8000-000000000006"
UNKNOWN_EXCEPTION_REQUEST_ID = "00000000-0000-4000-8000-000000000007"
UNKNOWN_RELOCATION_REQUEST_ID = "00000000-0000-4000-8000-000000000008"
UNKNOWN_NEIGHBORHOOD_ID = "00000000-0000-4000-8000-000000000009"
UNKNOWN_SEAT_ALLOCATION_ID = "00000000-0000-4000-8000-00000000000a"
UNKNOWN_DESK_ASSIGNMENT_ID = "00000000-0000-4000-8000-00000000000b"
UNKNOWN_ESCALATION_CASE_ID = "00000000-0000-4000-8000-00000000000c"
UNKNOWN_RECALIBRATION_REVIEW_ID = "00000000-0000-4000-8000-00000000000d"
