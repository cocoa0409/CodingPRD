"""Business constants for the in-office DME dispensing and bracing API.

Every value here is taken from the PRD: the API prefix, the logical-clock
startup instant, the six roles, the state vocabularies of the two encounter
dimensions and of every subordinate machine, and the pricing / window
constants used by the money and posture rules.
"""

# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------
API_PREFIX = "/dme"
CLOCK_PATH = "/_clock/set_current_utc"

# --------------------------------------------------------------------------
# Logical clock (PRD: the clock's startup value is exactly this instant)
# --------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLE_PRACTICE_ADMIN = "PracticeAdmin"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_INVENTORY_MANAGER = "InventoryManager"
ROLE_INSURANCE_COORDINATOR = "InsuranceCoordinator"
ROLE_ORTHO_PHYSICIAN = "OrthoPhysician"
ROLE_DME_FITTER = "DmeFitter"

ALL_ROLES = [
    ROLE_PRACTICE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INVENTORY_MANAGER,
    ROLE_INSURANCE_COORDINATOR,
    ROLE_ORTHO_PHYSICIAN,
    ROLE_DME_FITTER,
]

# The two roles whose X-User-Id must resolve to a real domain row.
ENTITY_BACKED_ROLES = [ROLE_ORTHO_PHYSICIAN, ROLE_DME_FITTER]
# The four roles whose acting id is opaque to the server.
OPAQUE_ROLES = [
    ROLE_PRACTICE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INVENTORY_MANAGER,
    ROLE_INSURANCE_COORDINATOR,
]

# --------------------------------------------------------------------------
# Pagination (PRD: limit default 10, min 1, max 100; offset default 0, min 0)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Encounter clinical dimension
# --------------------------------------------------------------------------
CLINICAL_DRAFT = "DRAFT"
CLINICAL_DOCUMENTED = "DOCUMENTED"
CLINICAL_AWAITING_DEVICE = "AWAITING_DEVICE"
CLINICAL_RESERVED = "RESERVED"
CLINICAL_FITTED = "FITTED"
CLINICAL_DELIVERED = "DELIVERED"
CLINICAL_RETURN_PENDING = "RETURN_PENDING"
CLINICAL_RETURNED = "RETURNED"
CLINICAL_VOIDED = "VOIDED"

# --------------------------------------------------------------------------
# Encounter financial dimension
# --------------------------------------------------------------------------
FINANCIAL_UNVERIFIED = "UNVERIFIED"
FINANCIAL_VERIFIED = "VERIFIED"
FINANCIAL_NON_COVERED = "NON_COVERED"
FINANCIAL_AUTH_PENDING = "AUTH_PENDING"
FINANCIAL_AUTH_APPROVED = "AUTH_APPROVED"
FINANCIAL_AUTH_DENIED = "AUTH_DENIED"
FINANCIAL_ABN_ISSUED = "ABN_ISSUED"
FINANCIAL_SELF_PAY = "SELF_PAY"
FINANCIAL_BILLED = "BILLED"
FINANCIAL_REFUNDED = "REFUNDED"
FINANCIAL_WRITTEN_OFF = "WRITTEN_OFF"

# --------------------------------------------------------------------------
# Subordinate state machines
# --------------------------------------------------------------------------
PA_SUBMITTED = "SUBMITTED"
PA_APPROVED = "APPROVED"
PA_DENIED = "DENIED"
PA_PENDED = "PENDED"

ABN_ISSUED = "ISSUED"
ABN_SIGNED = "SIGNED"
ABN_DECLINED = "DECLINED"
ABN_VOIDED = "VOIDED"

FAB_SUBMITTED = "SUBMITTED"
FAB_IN_FABRICATION = "IN_FABRICATION"
FAB_READY_FOR_FITTING = "READY_FOR_FITTING"
FAB_ADJUSTMENT_REQUESTED = "ADJUSTMENT_REQUESTED"
FAB_ACCEPTED = "ACCEPTED"
FAB_SUPPLIER_HOLD = "SUPPLIER_HOLD"
FAB_CANCELLED = "CANCELLED"

RETURN_REQUESTED = "REQUESTED"
RETURN_RESTOCKED = "RESTOCKED"
RETURN_DESTROYED = "DESTROYED"
RETURN_REFIT_ISSUED = "REFIT_ISSUED"

# --------------------------------------------------------------------------
# Clinic dispensing posture and shelf posture
# --------------------------------------------------------------------------
DISPENSING_ACTIVE = "ACTIVE"
DISPENSING_RESTRICTED = "RESTRICTED"
DISPENSING_SUSPENDED = "SUSPENDED"

POSTURE_OK = "OK"
POSTURE_BELOW_PAR = "BELOW_PAR"
POSTURE_CRITICAL = "CRITICAL"
POSTURE_STOCKOUT = "STOCKOUT"

RESTRICTED_STOCKOUT_COUNT = 1
SUSPENDED_STOCKOUT_COUNT = 2

# --------------------------------------------------------------------------
# Compliance hold reasons
# --------------------------------------------------------------------------
HOLD_CLINIC_SUSPENDED = "CLINIC_SUSPENDED"
HOLD_SUPPLIER_QUALITY_HOLD = "SUPPLIER_QUALITY_HOLD"

# --------------------------------------------------------------------------
# Supervision, categories, privilege scopes
# --------------------------------------------------------------------------
SUPERVISION_DIRECT = "DIRECT"
SUPERVISION_GENERAL = "GENERAL"

CATEGORY_OFF_SHELF_PREFAB = "OFF_SHELF_PREFAB"
CATEGORY_CUSTOM_FITTED_PREFAB = "CUSTOM_FITTED_PREFAB"
CATEGORY_CUSTOM_FABRICATED = "CUSTOM_FABRICATED"

SCOPE_OFF_SHELF_ONLY = "OFF_SHELF_ONLY"
SCOPE_CUSTOM_AND_OFF_SHELF = "CUSTOM_AND_OFF_SHELF"

# --------------------------------------------------------------------------
# Money and window constants
# --------------------------------------------------------------------------
CASH_MULTI_UNIT_DISCOUNT_PCT = 0.15
CASH_DISCOUNT_MIN_QTY = 2
DISPENSING_FEE_CENTS = 2500
FEE_WAIVER_SUBTOTAL_CENTS = 50000

DEVICE_SHARE_PCT = 0.85
FITTING_FEE_SHARE = 0.5
NON_SELLABLE_FEE_PCT = 0.25

RESTOCK_WINDOW_DAYS = 30
RETURN_WINDOW_DAYS = {
    "POOR_FIT": 30,
    "PATIENT_REFUSED": 30,
    "DEFECT": 90,
    "WRONG_ITEM": 90,
}
REASON_FEE_PCT = {
    "DEFECT": 0.00,
    "WRONG_ITEM": 0.00,
    "POOR_FIT": 0.10,
    "PATIENT_REFUSED": 0.20,
}
REFIT_ELIGIBLE_REASONS = ["POOR_FIT", "WRONG_ITEM"]

LATE_DAY_PENALTY_POINTS = 4
ADJUSTMENT_PENALTY_POINTS = 6
TURNAROUND_SCORE_MAX = 100
TURNAROUND_SCORE_MIN = 0

MN_NOTE_VALIDITY_DAYS = 90
ADJUSTMENT_ROUND_LIMIT = 2
APPEAL_ROUND_LIMIT = 2
FITTING_CHANGEOVER_BUFFER_MINUTES = 15

# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"
REQUEST_ID_PREFIX = "req_"

# A syntactically valid UUID that is never minted by the server.
UNKNOWN_UUID = "00000000-0000-4000-8000-0000000000f1"
UNKNOWN_UUID_ALT = "00000000-0000-0000-0000-000000009999"
