"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Capacity estimation constants (PRD §3.3)
CELL_BASE_MBPS = {"EMBB": 900, "URLLC": 300, "MMTC": 60}
EIRP_REF_DBM = 40
ATTENUATION_FULL_LOSS_DB = 30
OPTIMISTIC_MARGIN_DB = 6
CONSERVATIVE_MARGIN_DB = 9
NEIGHBOR_PENALTY_PCT = 5
NEIGHBOR_RADIUS_M = 500
NEIGHBOR_CAP = 3

# Attenuation factor lookup by building material class (PRD §3.2)
ATTENUATION_BY_MATERIAL = {
    "OPEN": 3,
    "WOOD": 6,
    "CONCRETE": 12,
    "STEEL": 18,
    "MIXED": 10,
}

# Required cell count (PRD §3.3)
CELL_COVERAGE_SQM = 5000
MATERIAL_PENALTY_FLOOR = 0.25

# Survey approval threshold (PRD §3.2)
RSRP_APPROVAL_MIN_DBM = -110

# Minimum viable design target capacity (PRD §3.3)
MIN_TARGET_CAPACITY_MBPS = 100

# Interference report constants (PRD §3.4)
COORDINATION_RADIUS_M = 1000
FSPL_CONST_DB = 32.44
NO_NEIGHBOR_MARGIN_DB = 99

# SLA breach credit (PRD §3.8)
SLA_MONTHLY_FEE_CENTS = 100000
SLA_CREDIT_RATES = {
    "STANDARD": 0.05,
    "ENHANCED": 0.10,
    "MISSION_CRITICAL": 0.20,
}

# PAL frequency bucket half-width (PRD §3.4)
PAL_FREQUENCY_BUCKET_MHZ = 10

# Contract renewal window (PRD §3.8)
RENEWAL_WINDOW_DAYS = 30

# Logical clock default (PRD §2.5)
DEFAULT_LOGICAL_TIME = "2026-09-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

TEST_DEFAULTS = {
    "TARGET_CAPACITY_MBPS": 1000,
    "SITE_AREA_SQM": 2000,
    "TARGET_AVAILABILITY_PCT": 99.9,
}
