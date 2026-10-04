"""Domain thresholds and reference values taken from the PRD.

Every number here is a constant the PRD names explicitly, or a value the PRD's
worked examples pin. Nothing here is invented.
"""

# --- Standardization and letter cut-offs -------------------------------------
STANDARDIZATION_MIDPOINT = 50.00
STANDARDIZATION_SPAN = 15.00
SCORE_FLOOR = 0.00
SCORE_CEILING = 100.00
COMPOSITE_ROUND_DP = 2
DOMAIN_ROUND_DP = 2
MEASURE_ROUND_DP = 1

CUT_A = 85.00
CUT_B = 62.50
CUT_C = 45.00
CUT_D = 30.00
RELIABILITY_CAP_THRESHOLD = 0.60

DOWNGRADE = {"A": "B", "B": "C", "C": "D", "D": "F", "F": "F"}
LETTER_RANKS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}

# --- Reliability ------------------------------------------------------------
SAMPLE_RATE_FULL = 0.50
SAMPLE_RATE_PARTIAL = 0.25
BASE_FULL = 1.00
BASE_PARTIAL = 0.60
BASE_NONE = 0.00
RESPONDENT_SCALE_CAP = 500
COVERAGE_FLOOR = 0.50
VERIFICATION_FLOOR = 0.10

# --- Comparability ----------------------------------------------------------
COMPARABILITY_FLOOR = 0.80
INDEX_ROUND_DP = 4

# --- Derivation -------------------------------------------------------------
INVERSE_BOUND = 1.00
BED_DIVISOR = 100

# --- Reanalysis -------------------------------------------------------------
DROPPED_MEASURE_POINT_PENALTY = 4.00
SAFE_PRACTICE_REQUIRED_CREDIT_COUNT = 8
SAFE_PRACTICE_REQUIRED_DOCUMENT_CODE_COUNT = 10
REANALYSIS_MIN_DOCUMENT_CODES = 6
REANALYSIS_MAX_SELECTORS = 20
REANALYSIS_REGRESSION_FLOOR = -0.01

# --- Measure set ------------------------------------------------------------
OMISSION_SUBSTITUTED_THRESHOLD = 4

# --- Employer ---------------------------------------------------------------
PROPENSITY_BASE = 34.00
PROPENSITY_SLOPE = 0.60
PROPENSITY_MIDPOINT = 50.00

# --- Temporal ---------------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"
CYCLE_PUBLICATION_BUFFER_DAYS = 30

# --- Reference document codes ----------------------------------------------
DOCUMENT_CODES = [
    "HAND_HYGIENE",
    "ICU_STAFFING",
    "BARCODE_MED_ADMIN",
    "SAFE_SURGERY_CHECKLIST",
    "CAUTI_BUNDLE",
    "CLABSI_BUNDLE",
    "VTE_PROPHYLAXIS",
    "MRSA_SCREENING",
    "ANTIBIOTIC_STEWARDSHIP",
    "SEPSIS_PROTOCOL",
]

# Six distinct codes clear the documented-grant gate.
SIX_DOCUMENT_CODES = DOCUMENT_CODES[:6]
FIVE_DOCUMENT_CODES = DOCUMENT_CODES[:5]

# --- Reference instants -----------------------------------------------------
CLOCK_2026_06_01 = "2026-06-01T00:00:00Z"
CLOCK_2026_06_02 = "2026-06-02T00:00:00Z"
CLOCK_2026_06_29_LATE = "2026-06-29T23:59:59Z"
CLOCK_2026_06_30 = "2026-06-30T00:00:00Z"
CLOCK_2026_07_01 = "2026-07-01T00:00:00Z"
CLOCK_2026_07_10 = "2026-07-10T00:00:00Z"
CLOCK_2026_07_14_LATE = "2026-07-14T23:59:59Z"
CLOCK_2026_07_15 = "2026-07-15T00:00:00Z"

WINDOW_END = "2026-06-30T00:00:00Z"
PUBLICATION_DATE = "2026-07-15T00:00:00Z"

# --- Reference measure definitions ------------------------------------------
# The seven-measure reference methodology used by the worked examples. Its
# measure tree, weights, scale factors and peer distributions are fixed by the
# PRD's scoring narrative.
REFERENCE_MEASURE_DEFINITIONS = [
    {"measure_code": "psi90_value", "domain": "PATIENT_SAFETY", "scale_factor": 100.0,
     "weight": 0.30, "multiplier": 1.00, "peer_mean": 55.00, "peer_sd": 12.00,
     "higher_is_better": True, "derivation_rule": "RATE_TO_COUNT_FLOOR"},
    {"measure_code": "hai_cdiff_value", "domain": "INFECTION_PREVENTION", "scale_factor": 100.0,
     "weight": 0.20, "multiplier": 0.80, "peer_mean": 50.00, "peer_sd": 14.00,
     "higher_is_better": False, "derivation_rule": "NONE"},
    {"measure_code": "hai_mrsa_value", "domain": "INFECTION_PREVENTION", "scale_factor": 100.0,
     "weight": 0.20, "multiplier": 0.80, "peer_mean": 50.00, "peer_sd": 14.00,
     "higher_is_better": False, "derivation_rule": "NONE"},
    {"measure_code": "hai_clabsi_value", "domain": "INFECTION_PREVENTION", "scale_factor": 100.0,
     "weight": 0.20, "multiplier": 0.80, "peer_mean": 50.00, "peer_sd": 14.00,
     "higher_is_better": False, "derivation_rule": "NONE"},
    {"measure_code": "cpoe_order_entry_value", "domain": "CPOE", "scale_factor": 100.0,
     "weight": 0.15, "multiplier": 1.50, "peer_mean": 60.00, "peer_sd": 15.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "staffing_rn_hppd_value", "domain": "STAFFING", "scale_factor": 10.0,
     "weight": 0.25, "multiplier": 1.00, "peer_mean": 48.00, "peer_sd": 13.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "surgical_volume_value", "domain": "SURGICAL_VOLUME", "scale_factor": 5.00,
     "weight": 0.10, "multiplier": 0.75, "peer_mean": 52.00, "peer_sd": 16.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
]

# Reference submitted raw values for the seven-measure methodology.
REFERENCE_RAW_VALUES = {
    # PRD §3.4: under `RATE_TO_COUNT_FLOOR` "the derived value is the raw value
    # floored to a whole number", and PRD §3.5 then multiplies that *derived*
    # value by the `scale_factor`. A raw 1.0200 therefore floors to 1 and
    # scales to 100.0; the alternative raw 101.0000 floors to 101 and scales
    # to 10100.0, which the standardization clamp then pulls to 100.00 anyway,
    # so the fixture is expressed with the smaller raw value.
    "psi90_value": 1.0200,
    "hai_cdiff_value": 0.8000,
    "hai_mrsa_value": 0.7494,
    "hai_clabsi_value": 0.9452,
    "cpoe_order_entry_value": 0.9500,
    "staffing_rn_hppd_value": 3.7400,
    "surgical_volume_value": 0.0000,
}

REFERENCE_SOURCE_PROGRAMS = {
    "psi90_value": "CMS_HOSPITAL_COMPARE",
    "hai_cdiff_value": "NHSN",
    "hai_mrsa_value": "NHSN",
    "hai_clabsi_value": "NHSN",
    "cpoe_order_entry_value": "CMS_HOSPITAL_COMPARE",
    "staffing_rn_hppd_value": "CMS_HOSPITAL_COMPARE",
    "surgical_volume_value": "CMS_HOSPITAL_COMPARE",
}

# The pinned reference outcomes for that fixture.
REFERENCE_DOMAIN_SCORES = {
    "PATIENT_SAFETY": 100.00,
    "INFECTION_PREVENTION": 83.13,
    "CPOE": 95.00,
    "STAFFING": 37.40,
    "SURGICAL_VOLUME": 0.00,
}
REFERENCE_COMPOSITE = 71.62
REFERENCE_COMPOSITE_ALT = 71.62
REFERENCE_DOMAIN_INFECTION_ALT = 83.15

# A three-measure baseline methodology used for simple scoring fixtures.
# Five domains, one measure each: PRD §3.5 refuses a score run whose pinned
# version "definitions do not cover all five domains with positive weights"
# with `ERR_METHODOLOGY_INCOMPLETE`, so every scorable fixture must span all
# five domains. See BASELINE_MEASURE_CODES for the order a fixture reports them.
BASELINE_MEASURE_DEFINITIONS = [
    {"measure_code": "o1", "domain": "PATIENT_SAFETY", "scale_factor": 1.0,
     "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o2", "domain": "CPOE", "scale_factor": 1.0,
     "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o3", "domain": "STAFFING", "scale_factor": 1.0,
     "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o4", "domain": "INFECTION_PREVENTION", "scale_factor": 1.0,
     "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o5", "domain": "SURGICAL_VOLUME", "scale_factor": 1.0,
     "weight": 1.00, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
]

# A four-measure methodology with a fourth domain.
FOUR_MEASURE_DEFINITIONS = [
    {"measure_code": "o1", "domain": "PATIENT_SAFETY", "scale_factor": 1.0,
     "weight": 0.50, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o2", "domain": "CPOE", "scale_factor": 1.0,
     "weight": 0.30, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o3", "domain": "STAFFING", "scale_factor": 1.0,
     "weight": 0.20, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o4", "domain": "SURGICAL_VOLUME", "scale_factor": 1.0,
     "weight": 0.10, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
]

# A five-domain methodology for the reliability-weight fixtures, one measure per
# domain, so a score run over it clears §3.5's all-five-domains precondition.
FIVE_DOMAIN_MEASURE_DEFINITIONS = [
    {"measure_code": "o1", "domain": "PATIENT_SAFETY", "scale_factor": 1.0,
     "weight": 0.40, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o2", "domain": "CPOE", "scale_factor": 1.0,
     "weight": 0.30, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o3", "domain": "STAFFING", "scale_factor": 1.0,
     "weight": 0.20, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o4", "domain": "INFECTION_PREVENTION", "scale_factor": 1.0,
     "weight": 0.10, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
    {"measure_code": "o5", "domain": "SURGICAL_VOLUME", "scale_factor": 1.0,
     "weight": 0.10, "multiplier": 1.00, "peer_mean": 50.00, "peer_sd": 10.00,
     "higher_is_better": True, "derivation_rule": "NONE"},
]