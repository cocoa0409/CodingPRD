"""Domain thresholds — numeric constants from the PRD's calculations."""

# Logical clock startup default (PRD §2.5).
CLOCK_START = "2026-09-01T00:00:00Z"
# Canonical setup instant used by most fixtures.
CLOCK_SETUP = "2026-09-05T00:00:00Z"

THRESHOLDS = {
    # Freight-class ladder (PRD §3.1), inclusive on the lower class.
    "T_PARCEL": 40.00,
    "T_250": 70.00,
    "T_150": 100.00,
    "T_125": 150.00,
    # Parcel gate in whole inches.
    "PARCEL_GATE_IN": 165,
    # Damage triage (PRD §3.6).
    "STRUCTURAL_DMG_PCT": 40,       # strictly greater-than triggers FULL_REPLACEMENT
    "REPAIR_FLOOR_CENTS": 20000,    # inclusive floor for REPAIR
    # Chargeback allocation shares (PRD §3.6).
    "CONCEALED_REPLACEMENT_SHARE": 0.35,
    "VISIBLE_REPAIR_CLAWBACK": 0.40,
    # Order fee split (PRD §3.3).
    "SURCHARGE_PCT": 0.05,
    "HANDLING_LOAD_PCT": 0.08,
    # Promised date arithmetic (PRD §3.3 / §3.5).
    "HANDLING_DAYS": 2,
    "HUB_DWELL_DAYS": 1,
    "SLIP_PER_MISS_DAYS": 2,
    # Supplier compliance (PRD §3.7).
    "W_ON_TIME": 0.60,
    "W_CHARGEBACK": 0.40,
    "ROLLING_WINDOW": 5,
    "T_PROBATION": 70.00,
    "T_SUSPENDED": 50.00,
    "T_RECOVER": 80.00,
    # Return authorization (PRD §3.8).
    "REVERSE_HAUL_FACTOR": 1.20,
    "REFURB_PCT_DAMAGE": 0.10,
    "REFURB_PCT_BUYERS_REMORSE": 0.40,
    "REFURB_PCT_WRONG_ITEM": 0.90,
    "RETURN_APPROVE_WINDOW_DAYS": 45,
    "RETURN_EXPIRY_DAYS": 30,
    # Appointment window (PRD §3.5).
    "MIN_APPOINTMENT_DURATION_HOURS": 2,
}

# Cube-score weights (PRD §3.1).
CUBE_WEIGHTS = {
    "W_LONGEST": 0.45,
    "W_CUBE_ROOT": 0.30,
    "W_GIRTH": 0.25,
}

TEST_DEFAULTS = {
    "DECLARED_VALUE_CENTS": 80000,
    "LTL_BASE_RATE_CENTS": 40000,
    "LTL_PER_LB_RATE_CENTS": 50,
    "LTL_TRANSIT_DAYS": 3,
    "LINEHAUL_CAPACITY": 10,
}
