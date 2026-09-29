"""Domain types for the Pediatric PDN Authorization Staffing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    PAYER_REVIEWER = "PayerReviewer"
    CASE_MANAGER = "CaseManager"
    SCHEDULER = "Scheduler"
    CLINICAL_SUPERVISOR = "ClinicalSupervisor"
    NURSE = "Nurse"


class PlanType(str, Enum):
    MEDICAID_WAIVER = "MEDICAID_WAIVER"
    MEDICAID_MCO = "MEDICAID_MCO"
    COMMERCIAL = "COMMERCIAL"


class BillingEditRuleset(str, Enum):
    STANDARD_15MIN = "STANDARD_15MIN"
    STRICT_15MIN = "STRICT_15MIN"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOSPITALIZED = "HOSPITALIZED"
    DISCHARGED = "DISCHARGED"


class PlanOfCareStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AUTHORIZED = "AUTHORIZED"
    RETURNED = "RETURNED"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REDUCTION_NOTICED = "REDUCTION_NOTICED"
    UNDER_APPEAL = "UNDER_APPEAL"
    REDUCED = "REDUCED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class NurseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class LicenseType(str, Enum):
    RN = "RN"
    LPN = "LPN"


class Skill(str, Enum):
    TRACH = "TRACH"
    VENT = "VENT"
    FEEDING_TUBE = "FEEDING_TUBE"
    SEIZURE_RESCUE = "SEIZURE_RESCUE"


class CompetencyStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CaseStatus(str, Enum):
    PENDING_STAFFING = "PENDING_STAFFING"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"


class HoldReason(str, Enum):
    HOSPITALIZATION = "HOSPITALIZATION"
    INCIDENT_REVIEW = "INCIDENT_REVIEW"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    FAMILY_REQUEST = "FAMILY_REQUEST"


class SupervisoryStatus(str, Enum):
    CURRENT = "CURRENT"
    OVERDUE = "OVERDUE"


class StaffingStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    ESCALATED = "ESCALATED"
    PARENT_BACKUP = "PARENT_BACKUP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EvvStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    CLOCKED_IN = "CLOCKED_IN"
    VERIFIED = "VERIFIED"
    EXCEPTION = "EXCEPTION"


class EscalationTier(str, Enum):
    NONE = "NONE"
    TIER1_AGENCY_POOL = "TIER1_AGENCY_POOL"
    TIER2_PARENT_BACKUP = "TIER2_PARENT_BACKUP"
    TIER3_PAYER_NOTIFICATION = "TIER3_PAYER_NOTIFICATION"


class ShiftCancelReason(str, Enum):
    NONE = "NONE"
    CASE_HOLD = "CASE_HOLD"
    AUTH_REDUCTION = "AUTH_REDUCTION"
    AUTH_EXPIRY = "AUTH_EXPIRY"
    SCHEDULER = "SCHEDULER"
    COMPETENCY_REVOKED = "COMPETENCY_REVOKED"


class AssignmentCancelReason(str, Enum):
    NONE = "NONE"
    REPLACED = "REPLACED"
    CASE_HOLD = "CASE_HOLD"
    AUTH_REDUCTION = "AUTH_REDUCTION"
    AUTH_EXPIRY = "AUTH_EXPIRY"
    SCHEDULER = "SCHEDULER"
    COMPETENCY_REVOKED = "COMPETENCY_REVOKED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class TimesheetStatus(str, Enum):
    CAPTURED = "CAPTURED"
    EDITED = "EDITED"
    SUBMITTED = "SUBMITTED"
    BILL_ACCEPTED = "BILL_ACCEPTED"
    BILL_REJECTED = "BILL_REJECTED"
    VOIDED = "VOIDED"


class EvvMethod(str, Enum):
    GPS = "GPS"
    IVR = "IVR"
    MANUAL = "MANUAL"


class EditCode(str, Enum):
    EVV_EXCEPTION = "EVV_EXCEPTION"
    LATE_START = "LATE_START"
    MANUAL_ENTRY = "MANUAL_ENTRY"
    POST_EDIT = "POST_EDIT"


class IncidentCategory(str, Enum):
    HOSPITALIZATION = "HOSPITALIZATION"
    MEDICATION_ERROR = "MEDICATION_ERROR"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"
    FALL = "FALL"
    MISSED_VISIT = "MISSED_VISIT"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DisputeType(str, Enum):
    REDUCTION_APPEAL = "REDUCTION_APPEAL"
    DENIAL_APPEAL = "DENIAL_APPEAL"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"


class VisitOutcome(str, Enum):
    PASS = "PASS"
    DEFICIENT = "DEFICIENT"


class UtilizationBasis(str, Enum):
    PROJECTED = "PROJECTED"
    SETTLED = "SETTLED"


class ContinuityBasis(str, Enum):
    STRICT = "STRICT"
    BROAD = "BROAD"


class BillingDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
