"""Domain constants and enum spellings taken from the PRD.

One canonical spelling per symbol; every helper and test imports from here so
that no two call sites can disagree about an enum member's text.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLE_CLINIC_ADMIN = "ClinicAdmin"
ROLE_CLINICIAN = "Clinician"
ROLE_COLLABORATING_PHYSICIAN = "CollaboratingPhysician"
ROLE_FRONT_DESK_AGENT = "FrontDeskAgent"
ROLE_PATIENT = "Patient"

ALL_ROLES = [
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_COLLABORATING_PHYSICIAN,
    ROLE_FRONT_DESK_AGENT,
    ROLE_PATIENT,
]

# ---------------------------------------------------------------------------
# Presenting complaints (PRD §3.1)
# ---------------------------------------------------------------------------
COMPLAINT_SORE_THROAT = "SORE_THROAT"
COMPLAINT_EAR_PAIN = "EAR_PAIN"
COMPLAINT_UTI = "UTI"
COMPLAINT_RASH = "RASH"
COMPLAINT_FLU_LIKE = "FLU_LIKE"
COMPLAINT_SPORTS_PHYSICAL = "SPORTS_PHYSICAL"

COMPLAINT_CODES = [
    COMPLAINT_SORE_THROAT,
    COMPLAINT_EAR_PAIN,
    COMPLAINT_UTI,
    COMPLAINT_RASH,
    COMPLAINT_FLU_LIKE,
    COMPLAINT_SPORTS_PHYSICAL,
]

# ---------------------------------------------------------------------------
# Clinician credentials (PRD §3.1)
# ---------------------------------------------------------------------------
CREDENTIAL_NP = "NP"
CREDENTIAL_PA = "PA"
CREDENTIALS = [CREDENTIAL_NP, CREDENTIAL_PA]

# ---------------------------------------------------------------------------
# Physician status (PRD §3.1)
# ---------------------------------------------------------------------------
PHYSICIAN_ACTIVE = "ACTIVE"
PHYSICIAN_INACTIVE = "INACTIVE"

# ---------------------------------------------------------------------------
# Staffing assignments (PRD §3.2)
# ---------------------------------------------------------------------------
ROLE_KIND_PRIMARY = "PRIMARY"
ROLE_KIND_FLOAT = "FLOAT"

ASSIGNMENT_SCHEDULED = "SCHEDULED"
ASSIGNMENT_ACTIVE = "ACTIVE"
ASSIGNMENT_COMPLETED = "COMPLETED"
ASSIGNMENT_CANCELLED = "CANCELLED"

ASSIGNMENT_STATUSES = [
    ASSIGNMENT_SCHEDULED,
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_CANCELLED,
]

# ---------------------------------------------------------------------------
# Clinic posture (PRD §2.8)
# ---------------------------------------------------------------------------
CLINIC_OPEN = "OPEN"
CLINIC_LIMITED = "LIMITED"
CLINIC_CLOSED = "CLOSED"
CLINIC_POSTURES = [CLINIC_OPEN, CLINIC_LIMITED, CLINIC_CLOSED]

# ---------------------------------------------------------------------------
# Queue entries (PRD §3.3)
# ---------------------------------------------------------------------------
QUEUE_KIND_WALK_IN = "WALK_IN"
QUEUE_KIND_APPOINTMENT = "APPOINTMENT"

QUEUE_SCHEDULED = "SCHEDULED"
QUEUE_WAITING = "WAITING"
QUEUE_CALLED = "CALLED"
QUEUE_SERVED = "SERVED"
QUEUE_ABANDONED = "ABANDONED"
QUEUE_DEFERRED_CLOSURE = "DEFERRED_CLOSURE"

QUEUE_STATUSES = [
    QUEUE_SCHEDULED,
    QUEUE_WAITING,
    QUEUE_CALLED,
    QUEUE_SERVED,
    QUEUE_ABANDONED,
    QUEUE_DEFERRED_CLOSURE,
]

# ---------------------------------------------------------------------------
# Visit — clinical dimension (PRD §3.4, §3.6, §3.8)
# ---------------------------------------------------------------------------
VISIT_SCREENING = "SCREENING"
VISIT_IN_ASSESSMENT = "IN_ASSESSMENT"
VISIT_TREATED = "TREATED"
VISIT_REFERRED = "REFERRED"
VISIT_CLOSED = "CLOSED"
VISIT_CANCELLED_CLOSURE = "CANCELLED_CLOSURE"

VISIT_CLINICAL_STATUSES = [
    VISIT_SCREENING,
    VISIT_IN_ASSESSMENT,
    VISIT_TREATED,
    VISIT_REFERRED,
    VISIT_CLOSED,
    VISIT_CANCELLED_CLOSURE,
]

# ---------------------------------------------------------------------------
# Visit — billing dimension (PRD §3.5, §3.8)
# ---------------------------------------------------------------------------
BILLING_UNBILLED = "UNBILLED"
BILLING_COVERAGE_VERIFIED = "COVERAGE_VERIFIED"
BILLING_SELF_PAY_QUOTED = "SELF_PAY_QUOTED"
BILLING_SELF_PAY_ACCEPTED = "SELF_PAY_ACCEPTED"
BILLING_INVOICED = "INVOICED"
BILLING_VOIDED = "VOIDED"

VISIT_BILLING_STATUSES = [
    BILLING_UNBILLED,
    BILLING_COVERAGE_VERIFIED,
    BILLING_SELF_PAY_QUOTED,
    BILLING_SELF_PAY_ACCEPTED,
    BILLING_INVOICED,
    BILLING_VOIDED,
]

# ---------------------------------------------------------------------------
# Coverage status (PRD §3.5)
# ---------------------------------------------------------------------------
COVERAGE_UNVERIFIED = "UNVERIFIED"
COVERAGE_ACTIVE = "ACTIVE"
COVERAGE_INACTIVE = "INACTIVE"
COVERAGE_UNKNOWN = "UNKNOWN"

# ---------------------------------------------------------------------------
# Assessment (PRD §3.6)
# ---------------------------------------------------------------------------
ASSESSMENT_DRAFT = "DRAFT"
ASSESSMENT_REFERRAL_REQUIRED = "REFERRAL_REQUIRED"
ASSESSMENT_TREATMENT_AUTHORIZED = "TREATMENT_AUTHORIZED"
ASSESSMENT_COSIGNED = "COSIGNED"

ASSESSMENT_STATUSES = [
    ASSESSMENT_DRAFT,
    ASSESSMENT_REFERRAL_REQUIRED,
    ASSESSMENT_TREATMENT_AUTHORIZED,
    ASSESSMENT_COSIGNED,
]

REFERRAL_EMERGENCY_DEPARTMENT = "EMERGENCY_DEPARTMENT"
REFERRAL_URGENT_CARE = "URGENT_CARE"
REFERRAL_PCP_FOLLOW_UP = "PCP_FOLLOW_UP"

REASON_RED_FLAG = "RED_FLAG"
REASON_HYPOXIA = "HYPOXIA"
REASON_FEVER_THRESHOLD = "FEVER_THRESHOLD"
REASON_TACHYCARDIA = "TACHYCARDIA"

# Positional precedence of the referral triggers (PRD §3.6)
REFERRAL_REASON_PRECEDENCE = [
    REASON_RED_FLAG,
    REASON_HYPOXIA,
    REASON_FEVER_THRESHOLD,
    REASON_TACHYCARDIA,
]

# Vitals ranges (PRD §3.6)
TEMP_C_MIN = 30.0
TEMP_C_MAX = 43.0
HEART_RATE_MIN = 20
HEART_RATE_MAX = 250
SPO2_MIN = 50
SPO2_MAX = 100

# ---------------------------------------------------------------------------
# Prescriptions (PRD §3.7)
# ---------------------------------------------------------------------------
THERAPY_ANTIBIOTIC_BETA_LACTAM = "ANTIBIOTIC_BETA_LACTAM"
THERAPY_ANTIBIOTIC_MACROLIDE = "ANTIBIOTIC_MACROLIDE"
THERAPY_ANALGESIC_NSAID = "ANALGESIC_NSAID"
THERAPY_ANTIHISTAMINE = "ANTIHISTAMINE"
THERAPY_CONTROLLED_OPIOID = "CONTROLLED_OPIOID"

THERAPY_CLASSES = [
    THERAPY_ANTIBIOTIC_BETA_LACTAM,
    THERAPY_ANTIBIOTIC_MACROLIDE,
    THERAPY_ANALGESIC_NSAID,
    THERAPY_ANTIHISTAMINE,
    THERAPY_CONTROLLED_OPIOID,
]

PRESCRIPTION_DRAFT = "DRAFT"
PRESCRIPTION_ROUTED = "ROUTED"
PRESCRIPTION_CANCELLED = "CANCELLED"

DAYS_SUPPLY_MIN = 1
DAYS_SUPPLY_MAX = 90
VALID_PHARMACY_NPI = "1234567890"

# ---------------------------------------------------------------------------
# Chart reviews (PRD §3.9)
# ---------------------------------------------------------------------------
REVIEW_PENDING = "PENDING"
REVIEW_CHANGES_REQUESTED = "CHANGES_REQUESTED"
REVIEW_ATTESTED = "ATTESTED"
REVIEW_ESCALATED = "ESCALATED"

REVIEW_STATUSES = [
    REVIEW_PENDING,
    REVIEW_CHANGES_REQUESTED,
    REVIEW_ATTESTED,
    REVIEW_ESCALATED,
]

SAMPLED_RANDOM_SAMPLE = "RANDOM_SAMPLE"
SAMPLED_MANDATORY_REFERRAL = "MANDATORY_REFERRAL"
SAMPLED_CONTROLLED_RX = "CONTROLLED_RX"

OUTCOME_WITHIN_SCOPE = "WITHIN_SCOPE"
OUTCOME_SCOPE_DEVIATION = "SCOPE_DEVIATION"

MAX_CHANGE_CYCLES = 2

# ---------------------------------------------------------------------------
# Visit summaries (PRD §3.9)
# ---------------------------------------------------------------------------
SUMMARY_QUEUED = "QUEUED"
SUMMARY_SENT = "SENT"
SUMMARY_FAILED = "FAILED"
SUMMARY_UNDELIVERABLE = "UNDELIVERABLE"

SUMMARY_STATUSES = [
    SUMMARY_QUEUED,
    SUMMARY_SENT,
    SUMMARY_FAILED,
    SUMMARY_UNDELIVERABLE,
]

DESTINATION_DIRECT_MESSAGE = "DIRECT_MESSAGE"
DESTINATION_FAX = "FAX"
DESTINATION_PATIENT_PORTAL = "PATIENT_PORTAL"

TRANSPORT_SENT = "SENT"
TRANSPORT_FAILED = "FAILED"

MAX_TRANSMIT_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Add-on services and their line prices (PRD §3.8)
# ---------------------------------------------------------------------------
SERVICE_RAPID_STREP_TEST = "RAPID_STREP_TEST"
SERVICE_URINALYSIS = "URINALYSIS"
SERVICE_INJECTION_ADMIN = "INJECTION_ADMIN"
SERVICE_EKG = "EKG"

SERVICE_PRICES_CENTS = {
    SERVICE_RAPID_STREP_TEST: 3500,
    SERVICE_URINALYSIS: 2800,
    SERVICE_INJECTION_ADMIN: 4200,
    SERVICE_EKG: 6500,
}

# ---------------------------------------------------------------------------
# Money (PRD §2.7, §3.5)
# ---------------------------------------------------------------------------
# Self-pay discount tiers keyed on the pre-discount subtotal.
SELF_PAY_TIER_LOW_LIMIT = 10000        # below this, no discount
SELF_PAY_TIER_MID_LIMIT = 20000        # below this, 10 percent
SELF_PAY_DISCOUNT_PCT_LOW = 0
SELF_PAY_DISCOUNT_PCT_MID = 10
SELF_PAY_DISCOUNT_PCT_HIGH = 15

OUTSTANDING_BALANCE_CEILING_CENTS = 50000

# ---------------------------------------------------------------------------
# Queue priority scoring (PRD §3.3)
# ---------------------------------------------------------------------------
ACUITY_POINTS_PER_TIER = 100
ON_TIME_APPOINTMENT_BONUS = 250
WAIT_POINTS_PER_MINUTE = 1
WAIT_POINTS_CAP = 180
VULNERABLE_AGE_BONUS = 60
VULNERABLE_AGE_YOUNG_MONTHS = 24
VULNERABLE_AGE_OLD_MONTHS = 780
PRIORITY_SCORE_CAP = 1000

# ---------------------------------------------------------------------------
# Wait-time projection (PRD §3.3)
# ---------------------------------------------------------------------------
POSTED_WAIT_CAP_MINUTES = 120
MINUTES_PER_WAITING_BLOCK = 20
MINUTES_PER_UPCOMING_APPOINTMENT = 10
APPOINTMENT_LOOKAHEAD_MINUTES = 60
ABANDON_AFTER_MINUTES = 120

# ---------------------------------------------------------------------------
# Appointment scheduling (PRD §3.3)
# ---------------------------------------------------------------------------
APPOINTMENT_SPACING_MINUTES = 30
ARRIVAL_WINDOW_EARLY_MINUTES = 15
ARRIVAL_WINDOW_LATE_MINUTES = 10

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
