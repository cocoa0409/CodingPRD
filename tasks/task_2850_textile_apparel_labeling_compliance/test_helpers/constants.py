"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock reads exactly this instant at server startup.
CLOCK_STARTUP = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # printable fiber string
    "ORNAMENTATION_LISTING_THRESHOLD_PCT": 5.0,
    # care performance verdict
    "CARE_MIN_CYCLES": 5,
    "CARE_MAX_SHRINKAGE_PCT": 3.0,
    "CARE_MIN_COLORFASTNESS": 3.5,
    # laboratory result coherence band
    "FIBER_SUM_MIN": 99.0,
    "FIBER_SUM_MAX": 101.0,
    # bench occupancy
    "LAB_BENCH_CAPACITY": 2,
    "CONDITIONING_BUFFER_HOURS": 24,
    # evidence validity horizons
    "FIBER_TEST_VALIDITY_DAYS": 365,
    "CARE_TEST_VALIDITY_DAYS": 730,
    # brand posture
    "PENALTY_SUSPEND_LEDGER_USD": 25000.00,
    "CRITICAL_FINDING_RESTRICT_THRESHOLD": 3,
    # marking penalty
    "PER_UNIT_PENALTY_USD": 1.25,
    "STATUTORY_CAP_RATE": 0.80,
    "REDELIVERY_WINDOW_DAYS": 30,
    "PROMPT_CORRECTION_WINDOW_DAYS": 10,
    "MITIGATION_RATE_PROMPT_FULL": 1.00,
    "MITIGATION_RATE_PARTIAL": 0.50,
    # audit findings
    "SEVERITY_ESCALATION_UNITS": 5000,
    # hangtag claims
    "ORGANIC_CLAIM_MIN_PCT": 95.0,
    "WRINKLE_FREE_MAX_SHRINKAGE_PCT": 2.0,
}

ESCALATION_BY_POSTURE = {"OPEN": 1.00, "RESTRICTED": 1.50, "SUSPENDED": 2.00}

PRODUCT_CLASS_DURABILITY_FACTOR = {
    "WOVEN_OUTERWEAR": 1.00,
    "KNIT_TOP": 1.25,
    "HOSIERY": 1.50,
    "HOME_TEXTILE": 0.80,
}

STAGE_RANK = {"TRIM": 0, "FIBER": 1, "YARN": 2, "FABRIC": 3, "CUT_AND_SEW": 4}

FIBER_CONTENT_METHODS = ["AATCC_20A", "ISO_1833"]
CARE_PERFORMANCE_METHODS = ["AATCC_135", "ISO_6330"]

ALL_ROLE_NAMES = [
    "ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
    "AccreditedLab", "CustomsOfficer", "Auditor",
]

TEST_DEFAULTS = {
    "MARKET_CODE": "US",
    "SECOND_MARKET_CODE": "CA",
    "LAB_CODE": "LAB-1",
    "SPECIMEN_RECEIVED_AT": "2026-08-01T09:00:00Z",
    "RESULTS_DUE_AT": "2026-08-02T09:00:00Z",
}
