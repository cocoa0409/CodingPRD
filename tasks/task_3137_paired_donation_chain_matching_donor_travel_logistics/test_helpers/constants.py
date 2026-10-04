"""Domain thresholds — numeric constants named in PRD prose.

Only constants whose values are stated in the PRD text are included here.
Constants named in the PRD without numeric values (e.g. probation
thresholds, slot lead time) are deliberately omitted — tests must derive
setup timing from observed server data (e.g. crossmatch_deadline_utc)
rather than hard-code unstated values.
"""

THRESHOLDS = {
    # Chain construction (PRD §3.3)
    "MIN_POOL_SIZE": 2,
    "MAX_CHAIN_LENGTH": 6,
    # Match score (PRD §3.4)
    "KDRI_MIN": 20,
    "KDRI_MAX": 250,
    "HLA_PENALTY_PER_LOCUS_BPS": 500,
    "WAIT_BONUS_PER_DAY_BPS": 5,
    "WAIT_BONUS_CAP_BPS": 1500,
    "PRIORITY_BOOST_BPS": 2000,
    "CPRA_BONUS_PER_PCT_BPS": 20,
    # Crossmatch decision (PRD §3.4)
    "DSA_PASS_THRESHOLD": 1000,
    "DSA_WEAK_THRESHOLD": 3000,
    # Cold ischemia (PRD §3.6)
    "COLD_ISCHEMIA_MAX_HOURS": 24,
    # Donor protection policy caps (PRD §3.9)
    "COMPLICATION_COVER_CENTS": 25000000,
    "LOST_WAGES_COVER_CENTS": 600000,
    # Travel reimbursement — base variant (PRD §3.10)
    "FLIGHT_CENTS_PER_MILE": 50,
    "FLIGHT_CAP_CENTS": 80000,
    "LODGING_PER_NIGHT_CENTS": 15000,
    "LODGING_CAP_CENTS": 60000,
    "FLAT_FEE_CENTS": 2500,
    # Travel reimbursement — altruistic variant (PRD §3.10)
    "ALTRUISTIC_MILEAGE_MULTIPLIER": 1.10,
    "FLIGHT_CAP_CENTS_ALTRUISTIC": 95000,
    "LODGING_CAP_CENTS_ALTRUISTIC": 75000,
    # Center reputation (PRD §3.7)
    "REPUTATION_BASE_BPS": 10000,
    "REPUTATION_FAILURE_PENALTY_BPS": 1500,
    "REPUTATION_FAILURE_CAP_BPS": 4500,
    "REPUTATION_CIT_PENALTY_BPS": 800,
    "REPUTATION_SHIPMENT_BONUS_BPS": 200,
    "REPUTATION_SHIPMENT_CAP_BPS": 1000,
}

# Default logical clock at server startup (PRD §1).
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
