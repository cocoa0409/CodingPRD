"""Domain thresholds and shared literals drawn from the PRD's stated rules.

Every value here is quoted or computed directly from the PRD prose; nothing is
invented.  Tests import these instead of scattering magic numbers.
"""

# --- Logical clock (PRD 2.4) -------------------------------------------------
# "The logical clock starts at exactly 2026-08-01T00:00:00Z."
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Loop caps and thresholds (PRD 3.1, 3.2, 3.4, 3.8) ----------------------
THRESHOLDS = {
    # PRD 3.1 - "a fourth submission is refused with ERR_PERMIT_ROUND_CAP"
    "PERMIT_ROUND_CAP": 3,
    # PRD 3.1 - egress_capacity = floor(egress_width_cm / 2.03)
    "EGRESS_CM_PER_PERSON": 2.03,
    # PRD 3.2 - revision_round cap
    "REVISION_ROUND_CAP": 3,
    # PRD 3.3 / 3.8 - kit condition floor shared by run creation and localisation
    "KIT_CONDITION_FLOOR": 60.00,
    # PRD 3.4 - clearance gates
    "STAFF_READINESS_MIN": 78.00,
    "STAFF_INCIDENT_MAX": 2,
    "REHEARSAL_TARGET_COUNT": 4,
    "MAX_SHIFT_MINUTES": 600,
    "SHIFT_REST_BUFFER_MINUTES": 30,
    # PRD 3.5 - dynamic price bounds and multipliers
    "PRICE_FLOOR_CENTS": 1000,
    "PRICE_CEILING_CENTS": 100000,
    "LEAD_EARLY_DAYS": 30,
    "LEAD_NORMAL_DAYS": 7,
    # PRD 3.6 - order shape and attendance
    "SINGLE_MAX_PARTY": 4,
    "GROUP_DISCOUNT_MIN_PARTY": 6,
    "MERCH_MAX_CENTS": 500000,
    "NO_SHOW_STRIKE_LIMIT": 3,
    "CHECKIN_GRACE_MINUTES": 15,
    "REFUND_FULL_HOURS": 72,
    "REFUND_HALF_HOURS": 24,
    # PRD 3.7 - inspection branches
    "EGRESS_MEASURE_FLOOR_PCT": 0.90,
    "MAJOR_FINDINGS_LIMIT": 5,
    "MINOR_FINDINGS_LIMIT": 2,
    # PRD 3.8 - demand gate and kit lifecycle
    "DEMAND_EXTENSION_FLOOR": 70.00,
    "REFURB_CAP": 2,
    "REFURB_RECOVERY": 30.00,
    "KIT_WEAR_BASE": 4.00,
    "KIT_WEAR_PER_MODULE": 0.30,
    "KIT_WEAR_CITY_MOVE": 9.00,
    "LOCALIZE_BASE_CENTS": 400000,
    "LOCALIZE_PER_MODULE_CENTS": 3300,
    "LOCALIZE_REUSE_DISCOUNT_PCT": 0.0270,
    "LOCALIZE_REUSE_CAP": 5,
}

# --- Pricing multipliers (PRD 3.5) ------------------------------------------
TIER_MULTIPLIERS = {
    "OFFPEAK": 0.80,
    "STANDARD": 1.00,
    "PEAK": 1.30,
    "PREMIUM": 1.60,
}

LEAD_MULTIPLIERS = {
    "EARLY": 0.90,   # lead_days >= 30
    "NORMAL": 1.00,  # 7..29
    "LATE": 1.15,    # < 7
}

LOYALTY_DISCOUNTS = {
    "VISITOR": 0.00,
    "MEMBER": 0.05,
    "PATRON": 0.12,
}

# --- Required certifications per staff role (PRD 3.4) -----------------------
REQUIRED_CERTIFICATIONS = {
    "PERFORMER": ["SCRIPTED_INTERACTION", "SENSORY_DEESCALATION"],
    "AMBASSADOR": ["SCRIPTED_INTERACTION", "ADA_ASSIST", "EVACUATION_MARSHAL"],
    "TECHNICIAN": ["RIGGING", "ELECTRICAL"],
}

# --- Handy literals reused by many setups ----------------------------------
TEST_DEFAULTS = {
    "CITY_CODE": "NYC",
    "BASE_TICKET_PRICE_CENTS": 35833,
    "TIMED_SLOT_MINUTES": 45,
    "MAX_GROUP_SIZE": 12,
    "EGRESS_WIDTH_CM": 400,
    "REQUESTED_OCCUPANCY_LOAD": 180,
    "BUILDOUT_ALLOWANCE_CENTS": 1500000,
    "BUILDOUT_CAP_CENTS": 3000000,
    "BASE_MONTHLY_RENT_CENTS": 4500000,
    "LEASE_START_DATE": "2026-08-01",
    "LEASE_END_DATE": "2027-01-31",
    "SCHEDULED_OPEN_DATE": "2026-08-10",
    "SCHEDULED_CLOSE_DATE": "2026-10-31",
    "TERM_START_DATE": "2026-08-01",
    "TERM_END_DATE": "2026-12-31",
    "MINIMUM_GUARANTEE_CENTS": 192790,
    "ROYALTY_RATE_BPS": 1250,
    "MERCH_ROYALTY_RATE_BPS": 750,
}

# A UUID-shaped identifier that is guaranteed to name no stored row.
UNKNOWN_UUID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
UNKNOWN_UUID_ALT = "ffffffff-ffff-4fff-8fff-ffffffffffff"
