"""
Business constants, enumerations and named literals of the retina
intravitreal-injection buy-and-bill contract.

Every value here is transcribed from the PRD; nothing is invented.  Tests import
these names so that a rule change shows up as one edit rather than fifty magic
numbers.
"""

# --------------------------------------------------------------------------
# Roles (§2.1)
# --------------------------------------------------------------------------
ROLE_PRACTICE_ADMIN = "PracticeAdmin"
ROLE_RETINA_SPECIALIST = "RetinaSpecialist"
ROLE_PHARMACY_TECH = "PharmacyTech"
ROLE_BILLING_SPECIALIST = "BillingSpecialist"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_PATIENT = "Patient"

ALL_ROLES = [
    ROLE_PRACTICE_ADMIN,
    ROLE_RETINA_SPECIALIST,
    ROLE_PHARMACY_TECH,
    ROLE_BILLING_SPECIALIST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PATIENT,
]

# The two roles whose X-User-ID must resolve to a stored row.
ENTITY_BACKED_ROLES = [ROLE_RETINA_SPECIALIST, ROLE_PATIENT]

# --------------------------------------------------------------------------
# Logical clock (§2.5)
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination (§2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Enumerations (§3)
# --------------------------------------------------------------------------
PAYER_TYPES = [
    "COMMERCIAL",
    "MEDICARE_ADVANTAGE",
    "MEDICARE_PART_B",
    "MEDICAID",
]
FEDERAL_PAYER_TYPES = ["MEDICARE_PART_B", "MEDICARE_ADVANTAGE", "MEDICAID"]

BIOSIMILAR_PREFERENCES = ["NONE", "PREFERRED", "MANDATORY"]
VIAL_TYPES = ["SINGLE_DOSE", "MULTI_DOSE_COMPOUNDED"]
COVERAGE_TIERS = ["PREFERRED", "NON_PREFERRED", "EXCLUDED"]
NOTIFICATION_CHANNELS = ["SMS", "EMAIL", "PHONE"]
CREDENTIALS = ["MD", "DO"]
EYES = ["OD", "OS"]
DISEASE_ACTIVITY = ["ACTIVE", "QUIESCENT"]

PLAN_STATUSES = [
    "DRAFT",
    "LOADING",
    "MAINTENANCE",
    "INTENSIFIED",
    "SUSPENDED",
    "DISCONTINUED",
]
TREATABLE_PLAN_STATUSES = ["LOADING", "MAINTENANCE", "INTENSIFIED"]
SUSPENSION_REASONS = [
    "ADVERSE_EVENT",
    "CLINICIAN_HOLD",
    "LOT_RECALL",
    "PATIENT_REQUEST",
]

AUTHORIZATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "INFO_REQUESTED",
    "APPROVED",
    "DENIED",
    "APPEALED",
    "EXHAUSTED",
    "EXPIRED",
]
AUTHORIZATION_DECISIONS = ["APPROVED", "DENIED", "INFO_REQUESTED"]
DENIAL_REASONS = [
    "STEP_THERAPY",
    "NOT_MEDICALLY_NECESSARY",
    "NON_FORMULARY",
    "INCOMPLETE_DOCUMENTATION",
]

LOT_STATUSES = ["AVAILABLE", "QUARANTINED", "RECALLED", "EXPIRED"]
VIAL_STATUSES = [
    "IN_STOCK",
    "RESERVED",
    "ADMINISTERED",
    "QUARANTINED",
    "RETURNED",
    "EXPIRED",
]

ENCOUNTER_STATUSES = ["DRAFT", "DOCUMENTED", "ATTESTED", "BILLED", "CLOSED", "VOIDED"]
ENCOUNTER_BILLABLE_STATUSES = ["DOCUMENTED", "ATTESTED", "BILLED", "CLOSED"]

CLAIM_LINE_STATUSES = [
    "PENDING",
    "SUBMITTED",
    "PAID",
    "DENIED",
    "APPEALED",
    "WRITTEN_OFF",
]

ENROLLMENT_PROGRAM_TYPES = [
    "MANUFACTURER_COPAY_CARD",
    "INDEPENDENT_FOUNDATION",
    "FREE_DRUG_PAP",
]
ENROLLMENT_STATUSES = ["PENDING", "ACTIVE", "EXHAUSTED", "TERMINATED", "EXPIRED"]

ADVERSE_EVENT_TYPES = [
    "ENDOPHTHALMITIS",
    "IOP_SPIKE",
    "RETINAL_DETACHMENT",
    "INTRAOCULAR_INFLAMMATION",
]
ADVERSE_EVENT_SEVERITIES = ["MILD", "MODERATE", "SEVERE"]
CULTURE_RESULTS = ["PENDING", "POSITIVE", "NEGATIVE"]
ADVERSE_EVENT_STATUSES = [
    "REPORTED",
    "UNDER_INVESTIGATION",
    "ADJUDICATED_RELATED",
    "ADJUDICATED_UNRELATED",
]
ADJUDICATION_OUTCOMES = ["RELATED", "UNRELATED"]

RECALL_CLASSES = ["CLASS_I", "CLASS_II", "CLASS_III"]
RECALL_STATUSES = [
    "INITIATED",
    "PATIENTS_NOTIFIED",
    "RETURN_SHIPPED",
    "CREDIT_RECONCILED",
    "CLOSED",
]
NOTIFICATION_STATUSES = ["PENDING", "SENT", "ACKNOWLEDGED", "UNREACHABLE"]

# --------------------------------------------------------------------------
# Named numeric constants
# --------------------------------------------------------------------------
# Disease activity (§3.2)
CST_ACTIVE_THRESHOLD_UM = 300

# Imaging validity window (§3.6)
IMAGING_VALIDITY_DAYS = 14

# Treat-and-extend (§3.3)
LOADING_INTERVAL_DAYS = 28
EXTENSION_STEP_DAYS = 14
REDUCTION_STEP_DAYS = 14
QUIESCENT_RUN_FOR_DOUBLE_STEP = 3

# Clinician day capacity (§3.6)
CAPACITY_WINDOW_HOURS = 24

# Lot exposure (§3.5)
CARRYING_RATE_BASIS_POINTS = 2000
BASIS_POINT_DIVISOR = 10000
DAYS_PER_YEAR = 365
BURN_WINDOW_DAYS = 30

# Responsibility waterfall (§3.8)
WRITEOFF_THRESHOLD_CENTS = 1000
FOUNDATION_HIGH_TIER_CENTS = 50000
LOW_TIER_CAP_FACTOR = 0.5
ADMINISTRATION_CPT_CODE = "67028"

# Adverse-event reportability (§3.9)
ENDOPHTHALMITIS_WINDOW_DAYS = 30
SEVERE_REPORT_DAYS = 15
ROUTINE_REPORT_DAYS = 30
ENDOPHTHALMITIS_QUARANTINE_THRESHOLD = 2
ENDOPHTHALMITIS_REPORTABLE_MAX_DAYS = 30

# Recall notification deadlines (§3.9)
RECALL_DEADLINE_DAYS = {"CLASS_I": 3, "CLASS_II": 10, "CLASS_III": 30}

# Exposure bases (§3.5)
BASIS_CARRYING = "CARRYING"
BASIS_EXPIRATION = "EXPIRATION"

# --------------------------------------------------------------------------
# Claim line dimensions (§3.8)
# --------------------------------------------------------------------------
DRUG_LINE_OUTCOMES = ["PAID", "DENIED", "WRITTEN_OFF"]
ADMIN_LINE_OUTCOMES = ["PAID", "DENIED"]
DENIAL_CODES = [
    "NOT_COVERED",
    "AUTHORIZATION_MISSING",
    "WASTAGE_NOT_PAYABLE",
    "DUPLICATE_CLAIM",
]

# --------------------------------------------------------------------------
# Lot vial counters (§2.9) - the six mutually exclusive custody counters
# --------------------------------------------------------------------------
LOT_COUNTER_FIELDS = [
    "vials_on_hand",
    "vials_reserved",
    "vials_administered",
    "vials_quarantined",
    "vials_returned",
    "vials_expired",
]

# --------------------------------------------------------------------------
# Probe identifiers used for the not-found walk (§2.8 step 6)
#
# Each key names one of the sixteen 404 families of the error catalogue and maps
# to the collection whose {id} path must produce it, plus a distinct unknown UUID
# so a mixed-up probe cannot accidentally hit a real row.
# --------------------------------------------------------------------------
UNKNOWN_UUID = "aaaaaaaa-0000-4000-8000-0000000000ff"

NOT_FOUND_PROBES = [
    ("/payers", "ERR_PAYER_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000001"),
    ("/drugs", "ERR_DRUG_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000002"),
    ("/payer-drug-policies", "ERR_POLICY_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000003"),
    ("/patients", "ERR_PATIENT_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000004"),
    ("/clinicians", "ERR_CLINICIAN_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000005"),
    ("/imaging-studies", "ERR_IMAGING_STUDY_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000006"),
    ("/treatment-plans", "ERR_PLAN_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000007"),
    ("/drug-lots", "ERR_LOT_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000008"),
    ("/vials", "ERR_VIAL_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000009"),
    ("/prior-authorizations", "ERR_AUTHORIZATION_NOT_FOUND", "aaaaaaaa-0000-4000-8000-00000000000a"),
    ("/injection-encounters", "ERR_ENCOUNTER_NOT_FOUND", "aaaaaaaa-0000-4000-8000-00000000000b"),
    ("/claims", "ERR_CLAIM_NOT_FOUND", "aaaaaaaa-0000-4000-8000-00000000000c"),
    ("/assistance-enrollments", "ERR_ENROLLMENT_NOT_FOUND", "aaaaaaaa-0000-4000-8000-00000000000d"),
    ("/adverse-events", "ERR_ADVERSE_EVENT_NOT_FOUND", "aaaaaaaa-0000-4000-8000-00000000000e"),
    ("/lot-recalls", "ERR_RECALL_NOT_FOUND", "aaaaaaaa-0000-4000-8000-00000000000f"),
    ("/recall-notifications", "ERR_NOTIFICATION_NOT_FOUND", "aaaaaaaa-0000-4000-8000-000000000010"),
]

# Void reasons written by cascades (§3.3, §3.7, §3.9)
VOID_REASON_PLAN_SUSPENDED = "PLAN_SUSPENDED"
VOID_REASON_LOT_RECALLED = "LOT_RECALLED"
