"""Domain thresholds and constants from the PRD's penalty/coverage specifications.

PRD §3.4 fixes the base amounts by risk factor and the compound adjustment
constants; §3.4 also fixes the gap-aggravation coverage threshold and the
recidivism rate/cap. The standard-library mapping is the PRD's applicability
model (§3.1): each function code maps to its standard set, and the union of
those sets across the registered functions is the entity's applicable set.
"""

# PRD §3.4: base amounts keyed by risk factor.
BASE_BY_VRF = {
    "MINIMAL": 1000.0,
    "MODERATE": 5000.0,
    "SERIOUS": 25000.0,
}

# PRD §3.4: compound adjustment constants.
SEVERE_MULTIPLIER = 2.0
HIGH_MULTIPLIER = 1.5
SELF_REPORT_DISCOUNT = 0.6
SELF_LOG_DISCOUNT = 0.4
GAP_AGGRAVATION = 1.25
RECIDIVISM_RATE = 0.1
RECIDIVISM_CAP = 5
COVERAGE_GAP_THRESHOLD = 0.8

# PRD §3.4: stale-violation final-penalty discount window (days) and factor.
STALE_VIOLATION_DAYS = 365
STALE_BASE_FACTOR = 0.9

# PRD §3.8: penalty due date is exactly thirty days after issuance.
PENALTY_DUE_DAYS = 30

# Standard library: the applicability mapping each function code expands to.
# Every function code in the design recipes uses two standards per code.
STANDARD_LIBRARY = {
    "GO": ["STD-GO-001", "STD-GO-002"],
    "GOP": ["STD-GOP-001", "STD-GOP-002"],
    "TO": ["STD-TO-001", "STD-TO-002"],
    "TOP": ["STD-TOP-001", "STD-TOP-002"],
    "TP": ["STD-TP-001", "STD-TP-002"],
    "BA": ["STD-BA-001", "STD-BA-002"],
    "RC": ["STD-RC-001", "STD-RC-002"],
    "IA": ["STD-IA-001", "STD-IA-002"],
    "PC": ["STD-PC-001", "STD-PC-002"],
    "DP": ["STD-DP-001", "STD-DP-002"],
    "LSE": ["STD-LSE-001", "STD-LSE-002"],
    "RP": ["STD-RP-001", "STD-RP-002"],
}

# PRD §1/§3.10: the logical clock defaults to this instant before any set call.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
