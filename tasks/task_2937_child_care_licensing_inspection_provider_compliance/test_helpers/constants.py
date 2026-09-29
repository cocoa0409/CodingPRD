"""Domain constants for the Child Care Licensing Compliance API.

Every value here is transcribed from the PRD: the statutory tables of §3.1-§3.9
and the global specifications of §2.3-§2.9.  Nothing here is guessed.
"""

# ─── §2.4 The logical licensing clock ──────────────────────────────────
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ─── §2.3 Pagination ───────────────────────────────────────────────────
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ─── Global statutory windows ──────────────────────────────────────────
SEGREGATION_LOOKBACK_MONTHS = 12
INSPECTION_MAX_REOPENS = 2
CAP_MAX_REVIEW_CYCLES = 3
CAP_SUBMISSION_WINDOW_DAYS = 10
POSTING_MAX_CORRECTIONS = 2
POSTING_RETENTION_MONTHS = 36
CLEARANCE_VALIDITY_MONTHS = 60
PROVISIONAL_PERIOD_MONTHS = 6
RISK_LOOKBACK_MONTHS = 24
REPEAT_LOOKBACK_MONTHS = 24
APPEAL_WINDOW_DAYS = 15
PROVIDER_VISIT_BUFFER_MINUTES = 60

# ─── §3.3 Clearance ────────────────────────────────────────────────────
REQUIRED_CHECK_TYPES = ["FBI_FINGERPRINT", "CHILD_ABUSE_REGISTRY"]

# ─── §3.1 Checklist catalog codes used by the cascades ─────────────────
CODE_SUPERVISION = "SU-101"
CODE_SUPERVISION_PLAN = "SU-102"
CODE_RATIO = "RA-201"
CODE_BACKGROUND = "BG-301"
CODE_FACILITY = "FA-401"
CODE_NUTRITION = "NU-501"
CODE_RECORDS = "RE-601"

# §3.7 fixed allegation-category -> checklist code mapping
COMPLAINT_CATEGORY_CHECKLIST_CODE = {
    "ABUSE": CODE_SUPERVISION,
    "SUPERVISION": CODE_SUPERVISION,
    "RATIO": CODE_RATIO,
    "BACKGROUND": CODE_BACKGROUND,
    "FACILITY": CODE_FACILITY,
    "NUTRITION": CODE_NUTRITION,
    "RECORDS": CODE_RECORDS,
}

# §3.7 the late-incident auto-citation always uses RE-601
LATE_INCIDENT_CHECKLIST_CODE = CODE_RECORDS

# ─── §3.2 Programme ceilings ───────────────────────────────────────────
CAPACITY_CEILING = {"CENTER": 120, "GROUP_HOME": 40, "FAMILY_HOME": 12}

# ─── §3.2 Statutory room tables ────────────────────────────────────────
STAFF_CHILD_RATIO = {"INFANT": 4, "TODDLER": 6, "PRESCHOOL": 10, "SCHOOL_AGE": 15}
AGE_GROUP_MAX_SIZE = {"INFANT": 8, "TODDLER": 12, "PRESCHOOL": 20, "SCHOOL_AGE": 30}

# ─── §3.5 Point assessment ─────────────────────────────────────────────
SEVERITY_BASE_POINTS = {"CRITICAL": 15, "SERIOUS": 8, "MODERATE": 4, "MINOR": 1}
INFANT_AGGRAVATION_FRACTION = 0.5
REPEAT_MULTIPLIER = {0: 1.0, 1: 2.0, 2: 3.0}
MAX_REPEAT_CHAIN_DEPTH = 2
MAX_POINTS_PER_CITATION = 30

# ─── §3.5 Compliance score ─────────────────────────────────────────────
EXPOSURE_WEIGHT = {
    "INFANT": 1.335,
    "TODDLER": 1.150,
    "PRESCHOOL": 1.000,
    "SCHOOL_AGE": 0.875,
}
STATUS_FACTOR = {
    "CITED": 1.000,
    "CORRECTION_PENDING": 1.000,
    "VERIFIED_CORRECTED": 0.400,
    "UNCORRECTED": 1.250,
    "VACATED": 0.000,
}
PERFECT_COMPLIANCE_SCORE = 100.00
VARIANT_PRELIMINARY = "PRELIMINARY"
VARIANT_FINAL = "FINAL"

# ─── §3.6 Correction allowances (days, per effective severity) ─────────
CORRECTION_ALLOWANCE_DAYS = {"CRITICAL": 3, "SERIOUS": 10, "MODERATE": 30, "MINOR": 45}

# ─── §3.5 Provider risk score ──────────────────────────────────────────
RISK_OPEN_POINTS_CAP = 60
RISK_WEIGHT_OPEN_POINTS = 1.0
RISK_WEIGHT_SUBSTANTIATED_COMPLAINT = 8
RISK_WEIGHT_INCONCLUSIVE_INTAKE_SCREENING = 0
RISK_WEIGHT_INCONCLUSIVE_ENFORCEMENT_REVIEW = 4
RISK_FLAT_CRITICAL_24MO = 10
RISK_FLAT_ADVERSE_STANDING = 15
RISK_SCORE_CAP = 100
VARIANT_INTAKE_SCREENING = "INTAKE_SCREENING"
VARIANT_ENFORCEMENT_REVIEW = "ENFORCEMENT_REVIEW"

# §3.5 risk tier bands: inclusive lower edge, exclusive upper edge
RISK_TIER_MODERATE_FLOOR = 20.0
RISK_TIER_HIGH_FLOOR = 45.0
RISK_TIER_SEVERE_FLOOR = 70.0

# ─── §3.7 Complaint priority matrix ────────────────────────────────────
YOUNG_BAND = ["INFANT", "TODDLER"]
OLDER_BAND = ["PRESCHOOL", "SCHOOL_AGE"]
COMPLAINT_BASE_PRIORITY = {
    ("ABUSE", "YOUNG"): "P1",
    ("ABUSE", "OLDER"): "P1",
    ("SUPERVISION", "YOUNG"): "P1",
    ("SUPERVISION", "OLDER"): "P2",
    ("RATIO", "YOUNG"): "P2",
    ("RATIO", "OLDER"): "P3",
    ("FACILITY", "YOUNG"): "P2",
    ("FACILITY", "OLDER"): "P3",
    ("NUTRITION", "YOUNG"): "P2",
    ("NUTRITION", "OLDER"): "P3",
    ("BACKGROUND", "YOUNG"): "P2",
    ("BACKGROUND", "OLDER"): "P2",
    ("RECORDS", "YOUNG"): "P3",
    ("RECORDS", "OLDER"): "P3",
}
COMPLAINT_ESCALATION = {"P3": "P2", "P2": "P1", "P1": "P1"}
INVESTIGATION_ALLOWANCE_DAYS = {"P1": 30, "P2": 45, "P3": 60}
AGENCY_INCIDENT_COMPLAINT_ALLOWANCE_DAYS = 30

# ─── §3.7 Serious incident reporting windows (hours) ───────────────────
INCIDENT_REPORTING_WINDOW_HOURS = {
    "FATALITY": 2,
    "MISSING_CHILD": 2,
    "SERIOUS_INJURY": 24,
    "MEDICATION_ERROR": 24,
    "COMMUNICABLE_DISEASE": 72,
}
INCIDENT_TYPES_REQUIRING_INVESTIGATION = ["FATALITY", "MISSING_CHILD"]
INCIDENT_ABUSE_CATEGORY_TYPES = ["FATALITY", "SERIOUS_INJURY", "MISSING_CHILD"]

# ─── §3.8 Enforcement ladder ───────────────────────────────────────────
LADDER_STEP = {"WARNING": 1, "PROBATION": 2, "SUSPENSION": 3, "REVOCATION": 4}
ENFORCEMENT_BASIS_MIN_POINTS = 15
LADDER_THRESHOLD_POINTS = {
    "WARNING": 15,
    "PROBATION": 30,
    "SUSPENSION": 45,
    "REVOCATION": 60,
}

# §3.8 fine arithmetic
FINE_BASE_CENTS = {
    "WARNING": 0,
    "PROBATION": 50000,
    "SUSPENSION": 150000,
    "REVOCATION": 500000,
}
FINE_CENTS_PER_BASIS_POINT = 2500
FINE_TIER_2_FLOOR_CENTS = 100000
FINE_TIER_3_FLOOR_CENTS = 300000
FINE_SURCHARGE_PCT = {1: 0, 2: 10, 3: 20}
FINE_CREDIT_PCT = {1: 0, 2: 5, 3: 15}

# ─── §3.9 Public register display ──────────────────────────────────────
POSTING_BANNER_BY_STEP = {
    0: "NONE",
    1: "WARNING",
    2: "PROBATION",
    3: "SUSPENSION",
    4: "REVOCATION",
}
POSTING_BANNER_PENALTY = {
    "NONE": 0.00,
    "WARNING": 2.00,
    "PROBATION": 5.00,
    "SUSPENSION": 10.00,
    "REVOCATION": 20.00,
}

# ─── Identifiers that resolve to nothing ───────────────────────────────
NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"
