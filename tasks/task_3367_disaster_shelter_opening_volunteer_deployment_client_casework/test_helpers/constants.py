"""Domain thresholds pinned by the PRD's calculation definitions."""

# Logical clock: the server's startup default.
CLOCK_START = "2026-09-01T00:00:00Z"
# The instant every shelter fixture advances to before opening a shelter.
CLOCK_ROTATION_START = "2026-09-03T00:00:00Z"

THRESHOLDS = {
    # shelter_operational_cost
    "OVERHEAD_RATE_BPS": 750,
    "MIN_OVERHEAD_CENTS": 2500,
    # client_assistance_entitlement
    "PER_PERSON_CENTS": 30000,
    "HOUSEHOLD_CAP_CENTS": 120000,
    "EXPEDITED_FLAT_CENTS": 20000,
    "EXPEDITED_MULTIPLIER_BPS": 5000,
    "EXPEDITED_CAP_CENTS": 150000,
    # duplication_of_benefits_offset
    "MIN_ASSISTANCE_CENTS": 5000,
    # volunteer_deployment_priority_score
    "BASE_SCORE": 100,
    "RECENCY_WINDOW_DAYS": 30,
    "RECENCY_MAX_BONUS": 30,
    "CANDIDATE_CROSS_REGION_MILES": 400,
    "CANDIDATE_SAME_REGION_MILES": 0,
    "MILES_PER_PENALTY_UNIT": 50,
    "DISTANCE_MAX_PENALTY": 25,
    "ROTATION_PENALTY_PER_DAY": 2,
    "ROTATION_MAX_PENALTY": 40,
    "ROLE_MATCH_BONUS": 20,
    # feeding_line_cost
    "SUPPLY_SURCHARGE_BPS": 625,
    # staffing_sufficiency
    "CLIENTS_PER_VOLUNTEER": 20,
    "MIN_REQUIRED_VOLUNTEERS": 1,
    "RESTRICTED_THRESHOLD": 0.60,
    # travel_cost_estimate (per-calculation mileage; travel pricing uses 120/400)
    "TRAVEL_SAME_REGION_MILES": 120,
    "TRAVEL_CROSS_REGION_MILES": 400,
    "AIR_BASE_CENTS": 45000,
    "AIR_DAY_SURCHARGE_CENTS": 2500,
    "AIR_SURCHARGE_FREE_DAYS": 14,
    "GROUND_RATE_CENTS_PER_MILE": 55,
    "GROUND_LODGING_PER_DAY_CENTS": 12000,
    "GROUND_LODGING_FREE_DAYS": 7,
    "SELF_CENTS": 0,
    # travel_lead_days
    "AIR_LEAD_DAYS": 1,
    "GROUND_LEAD_DAYS": 2,
    "SELF_LEAD_DAYS": 0,
    # blood_continuity_index
    "BLOOD_WINDOW_DAYS": 42,
    "BASELINE_TARGET_UNITS": 600,
    "STRAINED_THRESHOLD": 0.80,
    "CRITICAL_THRESHOLD": 0.50,
    "DEFERRAL_LOSS_BPS": 700,
    # dormitory_bed_assignment
    "BED_TURNOVER_BUFFER_MINUTES": 120,
    # redemption_window
    "STANDARD_WINDOW_DAYS": 90,
    "RESTRICTED_WINDOW_DAYS": 45,
    # case_closure_eligible_at
    "CLOSURE_HOLD_DAYS": 14,
    # credentialing / inspection / shift windows
    "CREDENTIAL_VALIDITY_DAYS": 30,
    "INSPECTION_VALIDITY_DAYS": 365,
    "NO_SHOW_GRACE_MINUTES": 240,
    "CHECK_IN_WINDOW_MINUTES": 60,
    "ROTATION_MAX_DAYS": 21,
    "ROTATION_MIN_DAYS": 1,
    "ANNUAL_ROTATION_CAP_DAYS": 40,
    "MAX_SHIFTS_PER_DEPLOYMENT": 3,
    "PAGE_DEFAULT_LIMIT": 10,
    "PAGE_MAX_LIMIT": 100,
}

# Values used to build payloads across the suite.
TEST_DEFAULTS = {
    "REGION_CODE": "GL",
    "REGION_NAME": "Great Lakes",
    "STATE_CODES": ["MI", "OH"],
    "COORDINATOR_USER_ID": "rc_gl",
    "VOLUNTEER_POOL_TARGET": 40,
    "AUTHORIZED_AGENCY_CODES": ["SALVATION_ARMY", "FEMA", "LOCAL_HOUSING"],
    "INCIDENT_CODE": "DR-9101",
    "INCIDENT_TYPE": "FLOOD",
    "DECLARED_AT": "2026-09-02T00:00:00Z",
    "FACILITY_NAME": "Lincoln High",
    "ADDRESS_LINE": "1 Main St",
    "CAPACITY_BEDS": 8,
    "AGREEMENT_EXPIRES_AT": "2027-09-01T00:00:00Z",
    "INSPECTED_AT": "2026-09-02T12:00:00Z",
    "VOLUNTEER_NAME": "Dana Ruiz",
    "VOLUNTEER_ROLES": ["SHELTER_MANAGER", "REGISTRATION", "FEEDING", "HEALTH_SERVICES"],
    "ROTATION_START_AT": "2026-09-03T00:00:00Z",
    "ROTATION_DAYS": 14,
    "CLIENT_NAME": "Ana Lopez",
    "HOUSEHOLD_SIZE": 5,
    "CASEWORKER_ID": "cw_1",
    "FINANCE_OFFICER_ID": "fo_1",
    "SECOND_FINANCE_OFFICER_ID": "fo_2",
    "OCCUPIED_FROM_AT": "2026-09-03T20:00:00Z",
}
